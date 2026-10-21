# When the laptop freezes and the RAM watcher did nothing

Written 2026-10-21 after the fourth hard freeze of October. This is a troubleshooting guide, not a
feature guide: it records how the freezes were read from the logs, why ollagi could not have prevented
them, and what was done about it, so the next freeze does not start from zero.

## What happened

The laptop (Lenovo IdeaPad L3 15IML05, 11.4 GiB RAM) froze completely four times in October 2026.
Each time the ollagi page had shown a green watcher and a RAM bar around 58 %. Each time the only way
out was holding the power button.

| Freeze | What the kernel logged last |
|---|---|
| Oct 9, 20:05 | zram decompression failed, then a crash inside `kswapd0` |
| Oct 13, 20:46 | zram decompression failed eight times in one second |
| Oct 18, 16:50 | swap entry counter went negative, then a crash in `zs_free`, "reboot is needed" |
| Oct 21, 20:54 | nothing at all; the journal just stops |

## How the logs were read

Everything came from `journalctl`. The useful commands, in the order they were run:

```
journalctl --list-boots                    # one line per boot; a boot that ends without a shutdown is a crash
last -x reboot shutdown                    # same idea from wtmp; "crash" marks a boot with no shutdown record
journalctl -b -1 -o short-iso | tail -60   # the last lines of the previous boot
journalctl -k -b -1 | grep -E 'Oops|BUG:|general protection|recursive fault'
journalctl -k -b -1 | grep -E 'Decompression failed|Read-error on swap|Bad rss'
coredumpctl list --since 2026-10-01        # user programs that crashed; a flurry of these can precede a kernel fault
```

`-b -1` means "the previous boot", `-b -2` the one before, and so on. `-k` keeps only kernel lines.

The chain in three of the four freezes was the same:

1. `zram: Decompression failed! err=-22`. The kernel asked zstd to unpack a compressed page and zstd
   said the data is garbage.
2. `Read-error on swap-device (252:0:...)`. The page could not be swapped back in.
3. `Bad rss-counter state ... MM_SWAPENTS val:-83`. The kernel's count of swapped pages went negative,
   which means its bookkeeping is corrupt.
4. An Oops in `zs_free` or `kswapd0`, then `Fixing recursive fault but reboot is needed!`, then a
   frozen screen.

On Oct 9 the same corruption showed up in user programs first: Claude Code crashed seven times, and
Brave, foot and pipewire once each, in the forty minutes before the kernel logged its first zram error.

## Why the RAM watcher could not act

The RAM bar on the page is used memory over total. 58 % used means about 4.8 GiB was still available.
The watcher goes red only below 0.75 GiB available or when programs are actually stalling on memory
(`/proc/pressure/memory` above 30 %). It was green, and it was right: the machine had not run out of
memory.

What broke was a page that had been compressed into zram hours earlier, during a heavy session, and
was read back at a calm moment. A corrupt compressed page bites whenever the kernel next touches it,
not when the pressure that wrote it was high. No program running in user space can see a kernel fault
coming or stop it. The watcher protects against running out of memory; this was something else.

## What zram is

zram is a compressed swap device that lives in RAM. When memory gets tight the kernel compresses idle
pages with zstd and keeps them in a reserved part of RAM instead of writing them to disk. It is fast
and it is the default on this install (`/usr/lib/systemd/zram-generator.conf.d/90-omarchy.conf`,
size equal to RAM, zstd, priority 100). There is also an ordinary swapfile on the encrypted disk at
priority 0, used only when zram is full.

Because zram stores compressed data in RAM, a single flipped bit in that RAM makes zstd reject the
whole page. That is why bad RAM shows up as "Decompression failed" and not as a plain wrong value.

## Two possible causes

- **Bad RAM.** `dmidecode -t memory` (needs sudo in a real terminal) showed two modules, both DDR4
  2667 MT/s, 1.2 V, single rank. Slot A: 4 GiB SK Hynix, part HMA851S6CJR6N-XN, soldered. Slot B:
  8 GiB, manufacturer code 89AB, part number blank. An unknown vendor code and an empty part number is
  the signature of a cheap no-name module. With 4 + 8 GiB the first 8 GiB is interleaved across both
  modules and the top 4 GiB lives only on the 8 GiB stick, so memtest errors above the 8 GiB mark would
  blame that stick alone.
- **A kernel bug.** The kernel was linux 7.2.3, installed 2026-09-11 and never updated; Arch core was
  at 7.2.11 by 2026-10-17. Against this: September boots on the same kernel swapped just as hard (peaks
  of 5.7 and 9.8 GB) and never logged a zram error.

The test that splits them is Memtest86+, which is installed (`/boot/memtest86+/memtest.efi`, EFI boot
entry "Memtest86+") and had not been run as of 2026-10-21.

## What was done on 2026-10-21

zram was switched off as a stopgap, so the failing code path is no longer used and the disk swapfile
carries all swap. Slower under pressure, but a bad page on disk swap does not take the kernel down
the same way.

```
sudo swapoff /dev/zram0 && sudo systemctl mask dev-zram0.swap
swapon --show        # should list only /swap/swapfile
```

To undo once the RAM question is settled:

```
sudo systemctl unmask dev-zram0.swap && sudo systemctl daemon-reload && sudo systemctl start dev-zram0.swap
```

## Still open

1. Run Memtest86+ overnight with the laptop plugged in. If it reports errors, note the address column.
2. If memtest fails: replace the 8 GiB stick with a branded DDR4-2666 SODIMM. Check Lenovo's spec
   sheet for the largest size this model takes before buying.
3. If memtest passes clean: update the kernel. zram can then be turned back on and watched.
4. If the machine freezes again with zram off, that points at the RAM regardless of memtest.

## Questions people ask

**Could ollagi have frozen the heavy session in time?** No. The machine was not short of memory when
it froze. The watcher's job is to stop sessions before memory runs out; it did not need to.

**Should the watcher go red earlier, say at 50 % used?** It would freeze sessions on a healthy machine
for no gain. The fix for a kernel fault is in the kernel or the hardware, not in a user program.

**Why did the Oct 21 freeze log nothing?** When the kernel locks up hard enough, the journal daemon
never gets to write the last lines to disk. The three earlier freezes logged their fault because the
kernel limped on for a few seconds first.

**Does disabling zram cost anything?** Yes: when RAM runs out, swapping goes to the encrypted disk and
the machine stutters instead of staying smooth. With zram off, the RAM bar and the watcher mean exactly
what they say, so the freeze action matters more, not less.
