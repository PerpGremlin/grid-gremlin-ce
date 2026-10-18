# Contributing

Findings first, code second — a failing spec is the best contribution there
is, and a pull request that carries one is the easiest to take.

## The shape of a change

- **One change, one pull request**, against `main`, with the spec that pins
  it: every invariant has a SPEC ID in `docs/SPEC.md` and a `spec_*` function
  in `tests/`; a guard has a sabotage spec that fails when the guard is
  removed. An error is a failure, never a skip.
- **The suite is green before anything merges:** `python3 tests/run.py`.
- **Standard library only.** No dependencies; that is a feature, keep it.
- **The words matter.** Error messages name only keys and values that exist;
  a thing on the screen is explained by the key page or it has failed.
- **Nothing reaches real money.** This edition refuses it in code (F21);
  a change that loosens that is not taken.
- **Nothing private.** No keys, account figures or hostnames in code, specs,
  fixtures or issues — redact them.

## What happens to a pull request

The suite runs on it automatically (the `specs` check); the owner reviews
and merges — nothing merges without that review. An accepted change is
then carried into the private edition this one is written from, so it
survives the next release.

## Nothing about you is needed

No name, email or phone number is asked for, in an issue or a pull request.
A GitHub account under any name will do; to keep your email out of your
commits, use GitHub's private `noreply` address (Settings → Emails). Your
findings are wanted; who you are is not.

## The licence of a contribution

By submitting a contribution you agree that it is licensed under the
Apache License 2.0, as the License itself says (section 5). No sign-off
line is needed.

## Where to look first

`docs/SPEC.md` for what is pinned, `docs/DECISIONS.md` for why, and
`docs/THREECOMMAS.md` for the ledger of mechanics — built, decided, or open.
