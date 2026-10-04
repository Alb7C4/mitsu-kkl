# Welcome to mitsu-kkl

This program reads data from the engine computer of older 1990s Mitsubishi cars (tested on a 1998 Eclipse 2.0).
It shows live sensor readings, such as engine speed, engine temperature, battery voltage and
accelerator position, and the fault codes.

**Especially useful for 1998–1999 model years**, which most ordinary diagnostic testers cannot connect to.
It also connects to European engine computers that the EvoScan program cannot talk to.

**The program only reads data. It never changes anything in the car.**

## What you need

- A Windows laptop.
- **The cheapest "VAG KKL 409.1" cable** (USB on one end, a plug for the car's diagnostic socket on the other).
  Don't buy more expensive "HEX", "VCDS" or "ELM327" adapters: they do not work with this car.
- **A short wire** that connects **pin 1** to **pin 4 or 5** in the diagnostic socket.
  Without it the car's computer does not answer. A small switch on the wire is handy.
  Looking at the socket in the car with its wider side up: pin 1 is the leftmost one in the top row,
  pins 4 and 5 are the fourth and fifth in the same row.

## Getting started

1. Plug the cable into the diagnostic socket under the dashboard and into the laptop's USB port.
2. Connect pin 1 to pin 4 or 5 with the wire.
3. Turn the key to ignition on. The engine does not need to run.
4. Click **Connect** in the program. After a few seconds the values in the list start changing.

The **ECU init** list next to the cable choice sets how the program wakes up the car's computer. Leave it on
**Auto**: the program tries the European way (0x00) and the American way (0x33, as EvoScan does) in turn
until the car answers.

The check-engine light may start blinking. That is normal: the car's computer shows its fault codes this way.

## If something doesn't work

- **"ECU not responding" appears at the top of the window:** check the wire on pin 1 and that the ignition is on.
- **The program doesn't find the cable:** plug the cable in again and click **Refresh**. You may need the driver from [ftdichip.com](https://ftdichip.com/drivers/).
- **Windows warns about the program on first start:** click "More info", then "Run anyway".

## Useful buttons

- **Fault Codes:** the fault codes, the same ones the check-engine light blinks.
- **● Record log:** saves the readings to a file you can open in Excel.
- When a new version is out, a bar with a download button appears at the top of the window.

Technical details and the full manual are on the [project page](https://github.com/Alb7C4/mitsu-kkl).

Use at your own risk. This program is not affiliated with Mitsubishi Motors.
