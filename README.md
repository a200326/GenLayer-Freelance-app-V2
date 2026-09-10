# Freelance Task Validator V2 — GenLayer Project

A full stack dApp for trustless freelance work verification with escrowed payment settlement, powered by GenLayer's AI consensus.

## Live Demo

**Try it now:** https://a200326.github.io/GenLayer-Freelance-app-V2/

Requires MetaMask connected to GenLayer Studionet.

## What It Does

Freelance work verification usually depends on one party's word against another and payment usually depends on trusting whoever holds the funds. This app removes both single points of trust: the payment is escrowed in the contract itself, multiple AI validators independently verify the submitted work and the consensus outcome directly and irreversibly determines who the escrowed funds belong to.

## How It Works

1. **Create Task** — a client defines a task, names a worker's wallet address and attaches a GEN payment that is held in escrow by the contract.
2. **Accept Task** — the worker explicitly confirms they accept the escrowed amount before doing any work. They can check the amount first and simply decline (or the client can cancel) if it doesn't match what was agreed off-chain.
3. **Submit Evidence** — the worker submits a URL pointing to their completed work. The evidence is fetched immediately and its content hash is committed on-chain by validator consensus.
4. **Verify & Resolve** — either the client or the worker can trigger verification. GenLayer validators independently refetch the evidence, check it against the committed hash and reach consensus on `approved` or `rejected`.
5. **Claim Payment / Raise Dispute** — if approved, either party can claim payment for the worker or the client can raise a dispute instead.
6. **Resolve Dispute** — either party can trigger arbitration. A second round of AI consensus decides `worker_wins` or `client_wins`, crediting the escrow accordingly.
7. **Withdraw** — the party owed funds withdraws their credited balance at any time.

Every state transition is enforced on-chain: only the registered worker can accept the task or submit evidence, only the client can cancel or raise a dispute and either party can advance a task that is stuck waiting on verification or arbitration.

## Enforceable Settlement

This milestone directly addresses steward feedback: *"let either party advance stalled tasks and connect the consensus outcome to an enforceable settlement rather than status labels alone."*

**Either party can advance stalled tasks.** `verify_and_resolve` and `resolve_dispute` can now be called by either the client or the worker, not just the client. This matters most when a previous attempt returned `fetch_failed`, `evidence_changed`, or `unparseable` and needs a retry, neither party is stuck waiting on the other.

**Consensus outcome is connected to real settlement, not just a label.** Payment is escrowed as real GEN at task creation (`@gl.public.write.payable`). The AI's verdict does not just set a status string, it determines who is credited a withdrawable balance (`pending_withdrawals`) and that credit is exactly the escrowed amount, enforced by the contract itself rather than trusted to either party.

**Pull-payment pattern.** Rather than the contract pushing a payment immediately (which can fail unpredictably and lock up state), the recipient calls `withdraw()` to claim their credited balance. This is a widely recommended security pattern for smart contracts (avoiding failed push payment lockups) and it also means the settlement *decision* is always safely and immediately finalized on-chain regardless of whether the actual token transfer can complete in the current environment (see Trust Model below).

## New in This Version

- `create_task` is now payable and requires a non zero escrow payment.
- `accept_task` — worker must explicitly accept the escrowed amount before submitting work.
- `cancel_task` — client can cancel and reclaim escrow before evidence is submitted.
- `claim_payment` — finalizes an approved, undisputed task by crediting the worker.
- `withdraw` — recipient claims their credited balance.
- `verify_and_resolve` and `resolve_dispute` can now be called by either the client or the worker.
- `get_amount` and `get_pending_withdrawal` — structured getters for escrow and settlement transparency.

## Trust Model & Limitations

- Evidence is trusted from a single URL provided by the worker. For stronger guarantees, use immutable sources (e.g. a pinned commit's raw file URL) rather than a branch URL that can change after submission.
- Evidence longer than 3000 characters is truncated; only the first 3000 characters are evaluated (exposed on-chain via `get_max_evidence_chars`).
- On any fetch, status, integrity or verdict-parsing failure, task state is left unchanged so either party can retry.
- **`withdraw()` requires the EVM/ghost-contract layer to deliver value to a plain wallet address.** This is available on live GenLayer networks (e.g. Bradbury) but not in the Studio sandbox, which has no EVM layer. All settlement *decisions* (escrow, crediting, entitlement) are fully testable and were tested end-to-end on Studio; only the final external token transfer requires a live network. The contract uses the documented pattern for this (`@gl.evm.contract_interface` wrapper around the recipient address) so `withdraw()` is ready to execute correctly once deployed to a network with the EVM layer.

## Setup

No build step required. This is a static HTML/JS application — open `index.html` directly in a browser or visit the live GitHub Pages link above.

## Contract

Network: GenLayer Studionet
Contract Address: `0xF64c4408dc72Fd7d4bc9bDf40435FDc83fe36EB9`

Explorer: https://explorer-studio.genlayer.com/address/0xF64c4408dc72Fd7d4bc9bDf40435FDc83fe36EB9

## Testing Instructions

1. Open the [live demo](https://a200326.github.io/GenLayer-Freelance-app-V2/).
2. Connect MetaMask (Studionet).
3. Create a task with your own address as the worker (so you can act as both roles for testing), attaching a GEN amount.
4. Accept the task (as worker), then submit an evidence URL, for example, a raw GitHub Gist link to a code file.
5. Click "Verify & Resolve" and confirm the transaction. Wait for AI consensus.
6. If approved, click "Claim Payment", then check your withdrawable balance and call "Withdraw".
7. To test arbitration, raise a dispute on an approved task, or verify a task with evidence AI is likely to reject, then resolve the dispute.

## Files

- `contract.py` — the GenLayer Intelligent Contract source.
- `index.html` — the complete frontend (deployed as-is to GitHub Pages).
