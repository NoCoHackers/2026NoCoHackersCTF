#include <stdio.h>

#include "common.h"

struct note {
    char message[32];
    void (*deliver)(void);
};

static void ordinary_delivery(void) {
    say("Sam: The scroll follows its ordinary path, far from the secret function.");
}

static void secret_delivery(void) {
    say("Sam: Well cast, apprentice! Your spell landed on the secret function.");
    say("A safe sorcerer limits their read to sizeof note.message, leaving its delivery function untouched.");
    print_flag("/flag/secret-tunnel.txt");
}

int main(void) {
    struct note note = {{0}, ordinary_delivery};

    setup();
    say("Sam: Apprentice, this scroll holds a 32-byte message followed by the function that sets its flight path.");
    say_pointer("My crystal ball reveals the secret function at %p.", (void *)secret_delivery);
    say("Binary runes cannot be typed literally. In Python, import struct, then struct.pack(\"<Q\", address).");
    say("Sam: The < rune means little-endian, and Q means an unsigned 64-bit value. Integrating this into a spell involving this challenge's socket is up to you to implement.");
    printf("Inscribe the scroll: ");
    read_inscription(note.message);
    note.deliver();
    return 0;
}
