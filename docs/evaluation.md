# Evaluation

The scorecard is pass or fail for five journeys. A journey fails if a required citation or amount is missing, if another tenant's marker appears, or if the narration mode is not the template. There is no similarity score and no invented accuracy percentage.

| Journey | Question | Pass condition |
| --- | --- | --- |
| Benefits | Is physical therapy covered, and how many visits? | Covered, 20 visits, 4 in 2026, 16 remaining, $30 copay, section 5.1. The 2025 visit is not counted. |
| Claims | Why do I owe $85 for my urgent care visit? | $75 copay from section 4.2 plus $10 deductible on EOB DEMO-1048. Member total 8500 cents. |
| Care | Find in-network cardiology options. | Patel and Chen, $50 specialist copay, section 6.1. Harbor is out of network and is omitted. |
| Action | Open a billing review request. | Case stays `pending_approval` until a reviewer approves. The member cannot approve. |
| Voice | Can you explain my latest claim? | Transcript in, latest EOB DEMO-1048 explained. Server speech recognizer not used. |

Run `python -m membercare.evals` after installing the package. The command prints JSON and exits non-zero when any journey fails. The same expectations are covered by `pytest`.

Partial payment is an extra claims check in the unit tests: EOB DEMO-2201, $400 submitted, $250 eligible, $160 benefit, $90 member amount from $50 deductible and $40 coinsurance. The coinsurance matches 20 percent of the eligible amount after the deductible in section 7.2.

The optional xAI wording pass is not part of the scorecard. The scorecard requires `narration` to be `template`.
