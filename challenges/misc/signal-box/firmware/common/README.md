# Shared RP2040 firmware support

Bare-metal boot2, startup, linker, register helpers, and UF2 packaging shared by
the signal-box DUT debug firmware and XIAO production tester. Register constants
come from the generated Pico SDK RP2040 headers supplied through
`PICO_SDK_PATH`; no Pico SDK runtime libraries are linked.

`boot2.S` is adapted from Raspberry Pi's BSD-3-Clause `boot2_generic_03h.S`.
