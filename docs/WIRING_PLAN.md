# Electrical wiring plan and safety boundary

This is a review-ready branch plan, not a final schematic. Part numbers, GPIOs,
fuse values, conductor sizes, gate polarity, and thermal limits must be frozen
from measured hardware before energizing the final enclosure.

## Exact power branches

```text
Certified enclosed 12 V DC / 3 A adapter
  positive -> master fuse -> latching master switch -> protected 12 V bus
  return   -------------------------------------------> 0 V bus

protected 12 V bus
  -> motor branch fuse
     -> TMC2209 VM input
        -> four motor-phase wires -> low-current NEMA 17

  -> candling branch fuse
     -> matched constant-current LED driver input
        -> driver LED output -> 3–5 W LED star on heatsink

  -> electronics branch fuse
     -> filtered 12 V-to-5 V buck input
        -> meter-verified 5.0 V output
           -> ESP32-S3 board 5 V input
           -> LCD/camera/microSD only through their board-approved rails

  -> optional reflected-light driver branch
     -> current-limited diffuse shell LED channel
```

**The ESP32-S3, camera, LCD, microSD, I/O expander, 3.3 V sensors, and 5 V
sensor rail must never receive 12 V.** The motor must never be powered from an
ESP32 pin. The 3–5 W LED must never connect directly to 12 V, a GPIO, or a plain
constant-voltage buck converter.

## Hard-wired cutoff chain

Use safety-rated contact arrangements appropriate to the reviewed prototype:

```text
enable-control supply
  -> latching emergency-stop NC contact A
     -> lid switch NC contact A
        -> hardware enable gate
           -> TMC2209 enable path
           -> candling-driver enable path
```

The ESP32 motor/light GPIOs are additional requests into that gate; they cannot
override an open NC contact. Both request nets require external pull-downs (or
the reviewed inactive polarity) so boot, reset, brownout, an unpowered ESP32,
and a disconnected cable mean disabled. A second isolated contact from each
interlock reports status to the ESP32. Reclosing the lid does not unlatch the
firmware fault and does not itself resume either load.

Whether the hard-wired gate removes driver `EN`, a load-switch enable, or both
must be decided from the actual selected LED driver and TMC2209 carrier. Verify
inactive polarity with the ESP32 physically unplugged.

## Signal and sensor rails

- TMC2209 `STEP`, `DIR`, and diagnostic/UART lines use reviewed logic levels;
  its motor supply remains on the fused 12 V branch.
- Hall-home, lid-sense pole B, E-stop-sense pole B, egg-presence, and LED
  temperature signals use the board-approved 3.3 V rail and protection.
- Do not assume Korvo-2 audio test points are free. Confirm the final schematic,
  boot strapping, LCD, camera, microSD, I/O expander, and reset behavior first.
- Join low-voltage references only where required by non-isolated drivers.
- Route motor phases away from camera, I2C, sensor, and LED-control wiring.
- Place bulk capacitance near the motor driver and local decoupling at every
  logic/sensor board; choose values after transient measurements.
- Use keyed, labeled connectors, strain relief, insulation, a removable spill
  tray, and a separate dry electronics compartment.

## Measurements required before enclosure closure

Record adapter no-load/load voltage, buck output, each branch current, stepper
RMS current, stall current, LED current, gate-off leakage, transient minima at
the ESP32 5 V input, heatsink temperature, egg/chamber temperature, and wire
temperature. Final fuses come from measured steady/inrush current and conductor
ampacity—not from the nominal adapter rating alone.
