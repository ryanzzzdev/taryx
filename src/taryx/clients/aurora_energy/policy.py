"""Aurora Energy — fictional retailer client policy.

Aurora runs the baseline au_nem retail catalogue unchanged, so its
policy identity stays the territory catalogue identity. Client identity
is selected at startup via TARYX_CLIENT, never from a request field.
"""

from taryx.territories.au_nem.tariffs import (
    CATALOGUE_VERSION as CATALOGUE_VERSION,
)
from taryx.territories.au_nem.tariffs import (
    GST_RATE as GST_RATE,
)
from taryx.territories.au_nem.tariffs import (
    POLICY_IDENTITY as POLICY_IDENTITY,
)
from taryx.territories.au_nem.tariffs import (
    TARIFFS as TARIFFS,
)

CLIENT_ID = "aurora_energy"
CLIENT_NAME = "Aurora Energy"

# Demo seed uses the shared deterministic specs; the overlapping account
# references/NMIs with the southgrid seed are deliberate — they expose
# accidental cross-client lookups rather than preventing collisions.
DEMO_SPECS = None
