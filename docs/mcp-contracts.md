# MCP contracts

Journey nodes still call the original plan, FHIR, provider, and case tools. The blueprint tool names live on three additional MCP servers in the same process. Every tool takes `actor_token`. The server derives the tenant and member from that token. A tool does not accept a member id from the model.

Money fields are decimal strings with two places. The lab does not put those amounts in a JSON float.

Success shape:

```json
{
  "tool": "get_eob_details",
  "schema_version": "1.0",
  "status": "success",
  "data": {
    "eob_id": "DEMO-1048",
    "claim_status": "complete",
    "currency": "USD",
    "provider_charge": "250.00",
    "allowed_amount": "180.00",
    "plan_paid": "95.00",
    "member_responsibility": "85.00"
  },
  "source": {
    "resource_type": "ExplanationOfBenefit",
    "resource_id": "DEMO-1048"
  }
}
```

`claim_status` is the FHIR `outcome` on the fixture (`complete`). An error returns the same envelope with `status` of `error` and an empty `data` object. A missing record and a record owned by another tenant both use `not_found`.

| Server | Tool | Side effect |
| --- | --- | --- |
| membercare-member-data | get_member_profile | Read |
| membercare-member-data | get_active_coverage | Read. A service date outside the loaded plan year returns `plan_year_mismatch` and no coverage body. |
| membercare-member-data | get_benefit_details | Read. Sets `binding_determination` to false. Unknown codes and other plan years return `evidence: insufficient` and no section. |
| membercare-member-data | list_member_eobs | Read |
| membercare-member-data | get_eob_details | Read |
| membercare-knowledge | search_policy_documents | Read. An effective date outside the loaded plan year returns no sections. |
| membercare-knowledge | search_providers | Read. Filters specialty, network, and city inside the actor tenant. |
| membercare-knowledge | get_provider_details | Read |
| membercare-member-actions | draft_billing_review | No case row. Writes an audit row. |
| membercare-member-actions | submit_billing_review | Opens a case only after a reviewer has approved it. A second submit returns the same case id. |
| membercare-member-actions | get_case_status | Read |

Retrieved plan text is data for the answer. It is not a system instruction and it cannot change tool permissions.
