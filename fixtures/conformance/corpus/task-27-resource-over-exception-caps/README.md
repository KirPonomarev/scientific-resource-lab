# task-27: Estimate over exception caps

Category: `resource-rejection` — Expected outcome: `REJECT_RESOURCE`

Pins that a plan whose summed SELECTED resource estimates exceed the exception caps raises `ResourceAdmissionError` (`WAIT_REMOTE_EXECUTOR`) — never silently overflowing local. Uses a synthetic available-adapter catalog so the steps are SELECTED, exactly as the WP-B14 gate does.
