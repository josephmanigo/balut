# Hardware bring-up gate

No energizing firmware build is authorized by this repository. Complete this
sequence with current-limited bench power and a reviewed schematic.

## Phase A — non-energized inspection

- Verify every adapter, driver, motor, LED, sensor, connector, and wire against
  the schematic and data sheets.
- Confirm polarity, continuity, absence of shorts, branch-fuse placement, earth
  or enclosure requirements, and strain relief.
- Verify 12 V cannot reach the ESP32/camera/LCD/microSD/5 V sensor rail.
- Confirm motor and light request nets have hardware-defined inactive states.
- Confirm the lid and E-stop each physically interrupt both enable paths.

## Phase B — electronics branch only

- Disconnect motor and candling branches.
- Current-limit the supply and power the 12-to-5 V buck alone.
- Meter the 5 V output before connecting the ESP32 board.
- Boot the non-energizing firmware; validate camera, LCD, microSD, buttons,
  sensors, watchdog, Wi-Fi, and logging without either high-power load.
- Measure boot/reset/brownout states at both enable request nets.

## Phase C — one branch at a time

- Connect the motor driver with no egg and tune current to the lowest reliable
  value. Verify home, commanded angle, incomplete-rotation detection, and stall.
- Separately connect the matched constant-current LED driver and heatsink. Tune
  pulse duration under temperature monitoring. Never bypass the driver.
- For each branch, open the lid and press E-stop during every active state.
  Confirm hardware removal with an oscilloscope or meter, not LCD text alone.

## Phase D — integrated guarded trials

- Perform empty-holder cycles before instrumented test eggs.
- Measure clamp force and use mechanical compression stops.
- Validate the engineering fiducial across egg sizes and quantify slippage.
- Confirm motor is off before light-on, light is off before motion, and exposure
  is locked only after settling.
- Run thermal, transient, cleaning/reassembly, and 100-cycle protocols from the
  validation ledger.

Only then may `BALUT_HARDWARE_ENERGIZING_BUILD` be proposed as `1` in a reviewed
hardware-specific branch. A firmware build cannot substitute for the physical
100/100 cutoff trials.
