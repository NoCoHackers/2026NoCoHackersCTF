# Sam's binary spellbook

Sam's lessons run on 64-bit x86 Linux (`amd64`). Download the source for your
lesson and read the fields in declaration order. The service discloses any code
address the intended solution needs, so you do not need to guess an address or
know the server's libc version.

## Text is not the same as bytes

Typing `\x64` sends four printable characters: backslash, `x`, `6`, and `4`.
An exploit often needs the single byte whose hexadecimal value is `64`, and
addresses usually contain `00` bytes that a terminal cannot type conveniently.
amd64 stores integer bytes least-significant first, a convention called little
endian. Sam states the Python encoding incantation during each lesson that needs
one.

## Sending binary runes

Your client must determine how to read through Sam's character-by-character
output, wait for the text menu before sending the lesson number, and wait for
the lesson's input prompt before sending binary bytes. That ordering matters:
Sam switches the connection into raw mode after reading the menu choice.
Sending everything at once can cause the terminal to consume or alter NUL bytes
before raw mode is active.

Sam treats a real newline as the end of a binary inscription but does not copy
that delimiter into lessons 2 or 3. Constructing the socket loop, recognizing
the prompts, combining padding with the encoded value, and appending the
newline are intentionally left to the reader.

## Mitigations in this teaching build

The lesson executables are non-PIE and omit stack canaries so each exercise can
focus on one memory-corruption concept. The stack remains non-executable (NX),
and the operating system may still randomize the stack and shared libraries.
That is why the return-address lesson reuses an existing function instead of
placing executable code on the stack. Real programs should combine correctly
bounded reads with compiler and platform mitigations rather than relying on a
single defense.
