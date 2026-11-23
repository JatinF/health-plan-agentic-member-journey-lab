# Security

This repository is a synthetic lab. It is not a health-plan system, and it is not a HIPAA or SOC 2 certification.

Do not open a pull request that adds real member records, real explanations of benefits, employer plan documents, or production credentials. The bearer tokens in `src/membercare/data/actors.json` are fixtures. They authorize nothing outside this process.

Member scope comes from the authenticated actor. A tool or route that receives an explanation-of-benefit id still checks the patient on that record. Cross-tenant reads use the same not-found response as a missing record.

A billing review draft does not open a case. Submit runs only for a reviewer, and only after the case is approved. Report a bypass of that gate as a defect in this lab.
