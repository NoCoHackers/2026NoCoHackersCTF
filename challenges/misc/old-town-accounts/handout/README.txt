OLD TOWN ACCOUNTS -- NIGHT COPY

old-town-accounts.rk is a bootable RK05 cartridge image containing a recovered
UNIX Fourth Edition filesystem. You may inspect it directly or boot your own
copy under a PDP-11 emulator. Becoming root on this archival copy is expected
and harmless; it is not the live accounting machine.

OpenSIMH example
----------------
Save the following as boot.ini beside old-town-accounts.rk, then run:

    pdp11 boot.ini

boot.ini:

    set quiet
    set cpu 11/45
    set tc enabled
    attach rk0 old-town-accounts.rk
    deposit sr 2
    send "k"
    expect "\r" send "unix\r"; go
    boot rk

The archival root account has no password. Do not add `set cpu idle` while
examining this image on the simulator console; long console transfers on this
historical kernel may starve under adaptive idling.

SHA-256
-------
c9c2a5c37e544735ac0eea9c64674257a8c65c44fe829cb10cc6165b6a028fbc  old-town-accounts.rk

Provenance and license
----------------------
This image was rebuilt from the recovered Utah UNIX V4 tape (original tape
SHA-256 43e912bb7a5fcc5f421eac30cf87b9e01417f547b248ce5f902fad14eb87b8a2)
and customized for NoCo Hackers CTF 2026. UNIX V4 redistribution is covered
by the accompanying Caldera license.

This product includes software developed or owned by Caldera International,
Inc.
