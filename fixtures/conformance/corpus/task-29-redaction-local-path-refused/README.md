# task-29: Packet containing local path marker refused

Category: `public-redaction` — Expected outcome: `REJECT_CONTRACT`

Pins the public boundary: a packet whose serialized form contains a local-filesystem path marker (`/Users/`, `/home/`, `C:\\Users\\`, `/etc/`) is refused — a public corpus never admits a packet that smuggles a local path.
