> **See CREATE_ENVIRONMENT.md** for the current, consolidated procedural guide covering this topic.

# Add a New Protocol / Interface

Example request:
「針對這份新規格與 DUT，建立新的 verification environment plugin。」

Harness flow:
LOCAL_ANALYSIS declaration
-> read Spec + RTL + registers + VIP docs
-> interface-schema-discovery
-> new-protocol-onboarding
-> protocol-plugin-generator
-> independent synthesis
-> plugin-compatibility-gate
-> compile
-> smoke test
-> self-repair
-> register plugin
-> use in Block/IP / Subsystem / Full SoC composer

If runtime verification is needed, transition explicitly to REMOTE_EXECUTION.
