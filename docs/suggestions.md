# Suggestions

Ideas that are not decided. Each says what it would change, why, and how to undo it. When one is
taken up, it becomes a decision in `docs/decisions/` and leaves this list.

## Reach the laptop more of the time

The page (and a Live terminal) can be reached from the phone only while the laptop is awake, I am
logged in, and Tailscale is up on both ends. Checked 2026-10-20: closing the lid suspends the
laptop (the journal shows a suspend at every lid close), and the ollagi service is a user service
with linger off, so after a reboot it starts only once I log in. A reboot also ends every session
(Claude's conversations stay on disk and can be resumed).

- **Stay awake with the lid closed while on the charger.** One line in logind's settings, needs
  sudo: a file `/etc/systemd/logind.conf.d/lid.conf` with `[Login]` and
  `HandleLidSwitchExternalPower=ignore`, then `sudo systemctl kill -s HUP systemd-logind`. On
  battery, closing the lid still suspends. Undo: delete the file and send HUP again.
  Cost: the laptop keeps using power and warming up in a bag if I close it while plugged in.
- **Start ollagi at boot, before I log in.** `loginctl enable-linger` keeps my user's services
  running without a login, so the page comes back after a reboot. Windows on the laptop (0017)
  still need me logged in. Undo: `loginctl disable-linger`.
  Cost: my services run from boot to shutdown, even when nobody uses the laptop.

## From the phone, 2026-10-22

All six taken up the same day: decisions 0029 to 0034.
