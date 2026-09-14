# Economic Bus

> Refreshed: 2026-08-27 · Code: `src/core/protocols.py` (`PaymentProvider`,
> `Quote`, `PaymentRequest`, `PaymentReceipt`),
> `src/core/adapters/payment_mock.py`,
> `src/core/adapters/payment_x402_shape.py`,
> `src/core/adapters/payment_x402.py`, `src/core/billing_adapter.py`

The economic bus abstracts money movement behind one interface so the core
runtime never talks to a payment vendor directly.

## PaymentProvider protocol

Legacy methods (unchanged): `record_usage / check_quota / settle_payment`.
Extended v0.1 methods:

| Method | Signature | Notes |
|--------|-----------|-------|
| `quote` | `(amount, currency, recipient, scheme) -> Quote` | price discovery |
| `request_payment` | `(PaymentRequest) -> PaymentReceipt` | idempotency via `metadata["idempotency_key"]` |
| `verify` | `(PaymentReceipt) -> bool` | settlement check |
| `refund` | `(PaymentReceipt) -> PaymentResult` | verify-before-refund in mock |

Dataclasses `Quote / PaymentRequest / PaymentReceipt` carry
`asset/network/amount/recipient/scheme/provider/metadata` — pure data, no
secrets.

## Providers shipped in v0.1

- **`BillingAdapter`** — wraps the internal MCU credit ledger. Legacy
  delegation unchanged; extended methods return explicit not-implemented
  results (MCU is an internal ledger, not a settlement rail).
- **`MockPaymentProvider`** — deterministic, idempotent (replayed
  idempotency keys return the same receipt; settled exactly once), no IO,
  no network, refund support.
- **x402-shape codec** (`payment_x402_shape.py`) — encodes/decodes the
  `PaymentRequired` 402 body and `X-PAYMENT` header shape as pure data
  (`scheme="exact"`, `x402Version=1`, integer-string atomic units).
  Decode rejects payloads containing key-like fields. The codec performs
  no network calls and holds no wallets.

## Added in v0.2: `X402SettlementProvider` (fail-closed)

`payment_x402.py` — a real settlement provider behind `PaymentProvider`,
fail-closed by construction:

- **Explicit config required** — endpoint/asset/network/recipient are ALL
  mandatory; missing or blank config raises `X402ConfigError` (never
  default-allow).
- **Governance-gated** — `settle_payment` / `request_payment` / `refund`
  go through `Governance.request_approval`; denial fails closed before any
  transport call.
- **Injected transport only** — the module opens no sockets itself; every
  network hop goes through the `X402Transport` callable supplied at build
  time. Tests inject a fake transport; no live rails.
- **Shape codec reuse** — quote/request payloads are encoded/decoded with
  `payment_x402_shape` (`scheme="exact"`); key-like fields are rejected and
  secrets are never logged.
- **Out of scope by design** — wallet creation, custody, key storage, real
  money. Settlement is confirmed only by the transport response.

## What is NOT allowed

The economic bus is deliberately incapable of:

1. **Custody** — no provider holds or moves funds on your behalf.
2. **Private keys / seed phrases / mnemonics** — forbidden fields; codecs
   reject them, tests assert they never leak into receipts or logs.
3. **Auto wallet creation** — no wallet generation anywhere in v0.1.
4. **Financial execution without explicit policy** — settlement requires a
   conformant provider wired by an operator; nothing auto-settles.
5. **Real money in tests** — every test uses the deterministic in-memory
   mock; no network, no live rails, no real currency.

## Protected production path (untouched)

NOWPayments IPN → tier activation remains mounted directly at
`src/gateway.py` and is protected: v0.1 does not remount it behind
`PaymentProvider`. That migration is deferred to a dedicated reviewed lane.

## Tests

`tests/test_payment_providers.py` (28 tests) covers quote/request/verify/
settle happy paths, invalid amount, wrong asset, wrong network, replay
idempotency, refund, and secret-leakage negatives;
`tests/test_economic_bus.py` asserts adapter conformance;
`tests/test_payment_x402_provider.py` (31 tests) covers the fail-closed
x402 provider: missing/blank config rejection, governance denial before
transport, injected-transport dispatch, replay rejection, secret-leakage
negatives, and refund gating.
