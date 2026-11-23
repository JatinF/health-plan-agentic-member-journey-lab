# Threat model

This is a local synthetic lab. The threats below are the ones the tests exercise. They are not a production payer assessment.

## Assets

Synthetic member records, plan-guide facts, and the billing-review status. The consequential action is opening a billing review.

## Boundaries

The browser sends a lab bearer token. That token is not an identity provider, and the tokens are in the repository on purpose so the demo can run. Do not copy this pattern into a system that holds real member data.

Tool calls receive the token from the authenticated request. The question text is not parsed for a token or a tenant. A member who asks for another tenant's claim still reads only their own explanations of benefits. A missing record and a record that belongs to someone else both return not found.

Reviewer and member are different actors. The member cannot approve. The open transition checks the case status in SQLite, so a resumed graph that claims approval without the approved row does not open the case.

Dollar amounts in the member sentence have to belong to the computed record set. The optional model wording pass is discarded when it introduces or drops a dollar amount. It is off unless both environment variables are set.

Checkpoints store the lab token used for the turn. That is acceptable here because the tokens are demo fixtures. It would not be acceptable for a real credential.

## Out of scope

Network exposure beyond loopback for the local module, malware scanning, a real IdP, and production audit retention. The container command listens on all interfaces because a container's loopback is not the host. That image was not built or run.

## Notice

`SYNTHETIC_MEMBER_DATA_NOT_A_HEALTH_PLAN`. No real member, plan, or patient system is connected.
