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

- **Answer a permission from the notification itself.** Allow and Deny buttons on a "needs you"
  notification (Notification `actions`); the service worker would POST the key to
  `/api/sessions/NAME/send`. Saves opening the app for a plain yes. Undo: remove the actions.
  Cost: a tap on the wrong button answers Claude without seeing the screen; the body text is cut
  to 500 characters, so the question may be incomplete.
- **Auto-name sessions started from the phone.** Leave the name empty and get
  `<folder>-<4 characters>` as `ollagi here` does. Undo: make the field required again.
- **A smaller font in the live terminal.** At 11 px the phone gives about 48 columns and Claude's
  boxes break; 9 px would give about 58, and a landscape phone about 100. A size button in the ⋯
  menu, remembered on the device. Undo: remove the button; the size falls back to 11.
- **Resume an earlier Claude conversation from the phone.** The New sheet could list recent
  conversations from Claude's own files (0016 already reads them) and start
  `claude --resume ID`. Undo: remove the list.
- **Stop redrawing the session list behind an open session.** `tick` rebuilds the list every 4 s
  while the viewer covers it. Keep fetching (the switcher needs it), skip the DOM work. Undo: one
  condition.
- **One scratch shell per project.** Start a terminal could reuse a running shell session in the
  same folder instead of making another. Undo: always start a new one.
