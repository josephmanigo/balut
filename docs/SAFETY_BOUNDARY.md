# Safety and claim boundary

## Non-negotiable hardware behavior

- The lid switch and emergency stop must physically remove motor-driver and candling-light enable, even if firmware is frozen.
- Motor and light request signals must be normally off during boot, reset, brownout, and disconnected GPIO states.
- Cloud services have no physical-control route.
- A fault requires acknowledgment and a fresh start; closing the lid alone never resumes motion.
- Twelve volts must never be applied directly to the ESP32-S3, camera, display, microSD, sensors, or a bare high-power LED.

The repository can model these requirements and test state transitions. It cannot prove the as-built circuit de-energizes safely.

## Claim language

Allowed machine language is limited to appearance and workflow:

- Day 16-like
- Day 18-like
- Reject—segregate and review
- Review or recapture
- Recorded incubation age
- Appearance mismatch

The system does not determine microbiological safety, pathogen status, edibility, lawful sellability, or disposal authority.

