# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
import json
import hashlib

FETCH_FAILED = "fetch_failed"
EVIDENCE_CHANGED = "evidence_changed"
UNPARSEABLE = "unparseable"
MAX_EVIDENCE_CHARS = 3000


@gl.evm.contract_interface
class _Recipient:
    class View:
        pass
    class Write:
        pass


def _fetch_text_evidence(url: str) -> str:
    try:
        resp = gl.nondet.web.request(url, method="GET")
    except Exception:
        return FETCH_FAILED

    status_code = None
    try:
        status_code = getattr(resp, "status_code", None)
    except Exception:
        status_code = None
    if isinstance(status_code, int) and not (200 <= status_code < 300):
        return FETCH_FAILED

    try:
        page_content = resp.body.decode("utf-8")[:MAX_EVIDENCE_CHARS]
    except Exception:
        return FETCH_FAILED

    if not page_content.strip():
        return FETCH_FAILED

    return page_content


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _parse_exact(raw: str, allowed: tuple) -> str:
    v = raw.strip().lower().strip(" \n\t.,!?'\"`")
    if v in allowed:
        return v
    return UNPARSEABLE


def _is_valid_address(addr: str) -> bool:
    if not addr.startswith("0x"):
        return False
    if len(addr) != 42:
        return False
    return True


def _is_valid_url(url: str) -> bool:
    u = url.strip().lower()
    return u.startswith("http://") or u.startswith("https://")


class FreelanceTaskValidator(gl.Contract):
    descriptions: DynArray[str]
    evidence_urls: DynArray[str]
    evidence_hashes: DynArray[str]
    amounts: DynArray[u256]
    statuses: DynArray[str]
    results: DynArray[str]
    verdicts: DynArray[str]
    clients: DynArray[str]
    workers: DynArray[str]
    task_count: u256
    pending_withdrawals: TreeMap[str, u256]

    def __init__(self):
        self.task_count = u256(0)

    def _require_task_exists(self, idx: int) -> None:
        if idx < 0 or idx >= int(self.task_count):
            raise gl.vm.UserError("Task does not exist")

    def _credit(self, to_address: str, amount: u256) -> None:
        # Credit a withdrawable balance to an address rather than
        # pushing a payment immediately. This is the pull-payment
        # pattern: the entitlement is locked in on-chain and final the
        # moment consensus is reached, but the actual native-token
        # transfer only happens when the recipient calls withdraw().
        # This avoids a failed/unsupported outbound transfer ever
        # corrupting task state - the settlement decision itself is
        # always safely recorded regardless of network capability.
        if to_address in self.pending_withdrawals:
            self.pending_withdrawals[to_address] = self.pending_withdrawals[to_address] + amount
        else:
            self.pending_withdrawals[to_address] = amount

    @gl.public.write
    def withdraw(self) -> None:
        # Sends any credited balance to the caller. Uses an external
        # (chain-layer) message via an EVM contract-interface wrapper,
        # which is the documented way to move native GEN from an
        # Intelligent Contract to a plain wallet address. Note: this
        # requires the EVM/ghost-contract layer, which is available on
        # live GenLayer networks but not in the Studio sandbox - see
        # README for details.
        caller = str(gl.message.sender_address).lower()
        if caller not in self.pending_withdrawals or self.pending_withdrawals[caller] == u256(0):
            raise gl.vm.UserError("No pending withdrawal for this address")

        amount = self.pending_withdrawals[caller]
        self.pending_withdrawals[caller] = u256(0)
        _Recipient(Address(caller)).emit_transfer(value=amount)

    @gl.public.write.payable
    def create_task(self, worker: str, description: str) -> None:
        worker_lower = worker.strip().lower()
        if not _is_valid_address(worker_lower):
            raise gl.vm.UserError(
                "worker must be a valid 0x-prefixed 40-hex-character address"
            )
        if description.strip() == "":
            raise gl.vm.UserError("description must not be empty")

        amount = gl.message.value
        if amount == 0:
            raise gl.vm.UserError(
                "create_task requires a non-zero payment to hold in escrow"
            )

        caller = str(gl.message.sender_address).lower()
        self.descriptions.append(description)
        self.evidence_urls.append("")
        self.evidence_hashes.append("")
        self.amounts.append(amount)
        self.statuses.append("open")
        self.results.append("")
        self.verdicts.append("")
        self.clients.append(caller)
        self.workers.append(worker_lower)
        self.task_count += u256(1)

    @gl.public.write
    def cancel_task(self, task_id: u256) -> None:
        idx = int(task_id)
        self._require_task_exists(idx)
        caller = str(gl.message.sender_address).lower()

        if self.statuses[idx] not in ("open", "accepted"):
            raise gl.vm.UserError(
                "Can only cancel a task before evidence has been submitted"
            )
        if caller != self.clients[idx]:
            raise gl.vm.UserError("Only the client can cancel this task")

        self._credit(self.clients[idx], self.amounts[idx])
        self.verdicts[idx] = "cancelled"
        self.results[idx] = "Task cancelled by client before evidence was submitted; escrow credited back to client - call withdraw() to claim."
        self.statuses[idx] = "refunded_client"

    @gl.public.write
    def accept_task(self, task_id: u256) -> None:
        # The worker explicitly confirms they accept the escrowed
        # amount before doing any work. This is a deliberate on-chain
        # acknowledgment step: the worker can check get_amount(task_id)
        # beforehand, and simply never call this (or the client can
        # cancel_task) if the escrowed amount doesn't match what was
        # agreed off-chain.
        idx = int(task_id)
        self._require_task_exists(idx)
        caller = str(gl.message.sender_address).lower()

        if self.statuses[idx] != "open":
            raise gl.vm.UserError("Task must be open to be accepted")
        if caller != self.workers[idx]:
            raise gl.vm.UserError("Only the worker can accept this task")

        self.statuses[idx] = "accepted"

    @gl.public.write
    def submit_evidence(self, task_id: u256, evidence_url: str) -> None:
        idx = int(task_id)
        self._require_task_exists(idx)
        caller = str(gl.message.sender_address).lower()

        if self.statuses[idx] != "accepted":
            raise gl.vm.UserError(
                "Task must be accepted by the worker before evidence can be submitted"
            )
        if caller != self.workers[idx]:
            raise gl.vm.UserError("Only the worker can submit evidence")
        if not _is_valid_url(evidence_url):
            raise gl.vm.UserError("evidence_url must be a valid http(s) URL")

        def fetch_and_hash() -> str:
            content = _fetch_text_evidence(evidence_url)
            if content == FETCH_FAILED:
                return FETCH_FAILED
            return _hash_content(content)

        content_hash = gl.eq_principle.strict_eq(fetch_and_hash)

        if content_hash == FETCH_FAILED:
            raise gl.vm.UserError(
                "Could not fetch the evidence URL at submission time. "
                "Make sure it is publicly reachable and try again."
            )

        self.evidence_urls[idx] = evidence_url
        self.evidence_hashes[idx] = content_hash
        self.statuses[idx] = "submitted"

    @gl.public.write
    def verify_and_resolve(self, task_id: u256) -> None:
        idx = int(task_id)
        self._require_task_exists(idx)
        caller = str(gl.message.sender_address).lower()

        if self.statuses[idx] != "submitted":
            raise gl.vm.UserError("Task must be submitted first")
        if caller != self.clients[idx] and caller != self.workers[idx]:
            raise gl.vm.UserError(
                "Only the client or worker for this task can trigger verification"
            )

        description = self.descriptions[idx]
        evidence_url = self.evidence_urls[idx]
        expected_hash = self.evidence_hashes[idx]

        def fetch_and_evaluate() -> str:
            page_content = _fetch_text_evidence(evidence_url)
            if page_content == FETCH_FAILED:
                return FETCH_FAILED

            if _hash_content(page_content) != expected_hash:
                return EVIDENCE_CHANGED

            prompt = f"""
You are a neutral evaluator for a freelance task.

Task description: {description}

Evidence content:
{page_content}

Has the task been completed satisfactorily?
Respond with EXACTLY one word and nothing else - no punctuation,
no explanation: approved or rejected
"""
            result = gl.nondet.exec_prompt(prompt)
            return _parse_exact(result, ("approved", "rejected"))

        verdict = gl.eq_principle.strict_eq(fetch_and_evaluate)

        if verdict == FETCH_FAILED:
            self.results[idx] = (
                "Evidence could not be verified: the URL did not return a "
                "successful text response. Task remains submitted; either "
                "the client or worker may retry verify_and_resolve once "
                "the URL is reachable."
            )
            return

        if verdict == EVIDENCE_CHANGED:
            self.results[idx] = (
                "Evidence integrity check failed: the content at this URL "
                "no longer matches the hash committed at submission time. "
                "Task remains submitted."
            )
            return

        if verdict == UNPARSEABLE:
            self.results[idx] = (
                "Validators could not produce a clear approved/rejected "
                "verdict. Task remains submitted; either party may retry "
                "verify_and_resolve."
            )
            return

        if verdict == "approved":
            self.verdicts[idx] = "approved"
            self.results[idx] = (
                "approved - funds remain in escrow until claim_payment is "
                "called or a dispute is raised"
            )
            self.statuses[idx] = "approved"
        else:
            self.verdicts[idx] = "rejected"
            self.results[idx] = "rejected"
            self.statuses[idx] = "disputed"

    @gl.public.write
    def raise_dispute(self, task_id: u256, reason: str) -> None:
        idx = int(task_id)
        self._require_task_exists(idx)
        caller = str(gl.message.sender_address).lower()

        if self.statuses[idx] != "approved":
            raise gl.vm.UserError("Can only dispute approved tasks")
        if caller != self.clients[idx]:
            raise gl.vm.UserError("Only the client can raise a dispute")
        if reason.strip() == "":
            raise gl.vm.UserError("reason must not be empty")

        self.results[idx] = "Disputed: " + reason
        self.verdicts[idx] = "disputed"
        self.statuses[idx] = "disputed"

    @gl.public.write
    def claim_payment(self, task_id: u256) -> None:
        # Finalizes settlement for an approved, undisputed task by
        # crediting the escrowed amount to the worker's withdrawable
        # balance. Either party may call this.
        idx = int(task_id)
        self._require_task_exists(idx)
        caller = str(gl.message.sender_address).lower()

        if self.statuses[idx] != "approved":
            raise gl.vm.UserError(
                "Task must be approved and undisputed to claim payment"
            )
        if caller != self.clients[idx] and caller != self.workers[idx]:
            raise gl.vm.UserError(
                "Only the client or worker for this task can claim payment"
            )

        self._credit(self.workers[idx], self.amounts[idx])
        self.results[idx] = "approved - payment credited to worker, call withdraw() to claim"
        self.statuses[idx] = "paid_worker"

    @gl.public.write
    def resolve_dispute(self, task_id: u256) -> None:
        idx = int(task_id)
        self._require_task_exists(idx)
        caller = str(gl.message.sender_address).lower()

        if self.statuses[idx] != "disputed":
            raise gl.vm.UserError("Task must be in disputed state")
        if caller != self.clients[idx] and caller != self.workers[idx]:
            raise gl.vm.UserError(
                "Only the client or worker for this task can resolve the dispute"
            )

        description = self.descriptions[idx]
        evidence_url = self.evidence_urls[idx]
        expected_hash = self.evidence_hashes[idx]
        dispute_reason = self.results[idx]

        def re_evaluate() -> str:
            page_content = _fetch_text_evidence(evidence_url)
            if page_content == FETCH_FAILED:
                return FETCH_FAILED

            if _hash_content(page_content) != expected_hash:
                return EVIDENCE_CHANGED

            prompt = f"""
You are a senior arbitrator reviewing a disputed freelance task.

Task description: {description}
Dispute reason: {dispute_reason}

Evidence content fetched directly from the submission URL:
{page_content}

Based on the task description and the evidence above, who should win?
Respond with EXACTLY one token and nothing else - no punctuation,
no explanation: worker_wins or client_wins
"""
            result = gl.nondet.exec_prompt(prompt)
            return _parse_exact(result, ("worker_wins", "client_wins"))

        verdict = gl.eq_principle.strict_eq(re_evaluate)

        if verdict == FETCH_FAILED:
            self.results[idx] = (
                "Evidence could not be verified during arbitration: the "
                "URL did not return a successful text response. Task "
                "remains disputed; either party may retry resolve_dispute."
            )
            return

        if verdict == EVIDENCE_CHANGED:
            self.results[idx] = (
                "Evidence integrity check failed during arbitration: the "
                "content no longer matches the hash committed at "
                "submission time. Task remains disputed."
            )
            return

        if verdict == UNPARSEABLE:
            self.results[idx] = (
                "Validators could not produce a clear worker_wins/"
                "client_wins verdict. Task remains disputed; either party "
                "may retry resolve_dispute."
            )
            return

        self.verdicts[idx] = verdict
        if verdict == "worker_wins":
            self._credit(self.workers[idx], self.amounts[idx])
            self.results[idx] = "worker_wins - payment credited to worker, call withdraw() to claim"
            self.statuses[idx] = "paid_worker"
        else:
            self._credit(self.clients[idx], self.amounts[idx])
            self.results[idx] = "client_wins - escrow credited back to client, call withdraw() to claim"
            self.statuses[idx] = "refunded_client"

    # ---- Structured getters for integrators ----

    @gl.public.view
    def get_status(self, task_id: u256) -> str:
        idx = int(task_id)
        self._require_task_exists(idx)
        return self.statuses[idx]

    @gl.public.view
    def get_verdict(self, task_id: u256) -> str:
        idx = int(task_id)
        self._require_task_exists(idx)
        return self.verdicts[idx]

    @gl.public.view
    def get_result(self, task_id: u256) -> str:
        idx = int(task_id)
        self._require_task_exists(idx)
        return self.results[idx]

    @gl.public.view
    def get_client(self, task_id: u256) -> str:
        idx = int(task_id)
        self._require_task_exists(idx)
        return self.clients[idx]

    @gl.public.view
    def get_worker(self, task_id: u256) -> str:
        idx = int(task_id)
        self._require_task_exists(idx)
        return self.workers[idx]

    @gl.public.view
    def get_description(self, task_id: u256) -> str:
        idx = int(task_id)
        self._require_task_exists(idx)
        return self.descriptions[idx]

    @gl.public.view
    def get_evidence_url(self, task_id: u256) -> str:
        idx = int(task_id)
        self._require_task_exists(idx)
        return self.evidence_urls[idx]

    @gl.public.view
    def get_evidence_hash(self, task_id: u256) -> str:
        idx = int(task_id)
        self._require_task_exists(idx)
        return self.evidence_hashes[idx]

    @gl.public.view
    def get_amount(self, task_id: u256) -> u256:
        idx = int(task_id)
        self._require_task_exists(idx)
        return self.amounts[idx]

    @gl.public.view
    def get_task(self, task_id: u256) -> str:
        idx = int(task_id)
        self._require_task_exists(idx)
        return (
            "status: " + self.statuses[idx] +
            " | verdict: " + self.verdicts[idx] +
            " | client: " + self.clients[idx] +
            " | worker: " + self.workers[idx] +
            " | result: " + self.results[idx]
        )

    @gl.public.view
    def get_task_count(self) -> u256:
        return self.task_count

    @gl.public.view
    def get_max_evidence_chars(self) -> u256:
        return u256(MAX_EVIDENCE_CHARS)

    @gl.public.view
    def get_pending_withdrawal(self, address: str) -> u256:
        addr = address.strip().lower()
        if addr in self.pending_withdrawals:
            return self.pending_withdrawals[addr]
        return u256(0)