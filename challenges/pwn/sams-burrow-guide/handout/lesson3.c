#include <stdio.h>

#include "common.h"

__attribute__((force_align_arg_pointer))
static void hidden_hutch(void) {
    say("Sam: Magnificent! The return address was over written and we landed in the hidden hutch.");
    say("A careful sorcerer bounds every write by the buffer's true size and checks how many bytes were read.");
    print_flag("/flag/return-to-hutch.txt");
    _exit(0);
}

static void follow_trail(void) {
    char steps[64];

    say("Sam: Every function call saves a return address telling it where execution should continue.");
    say("This buffer holds 64 bytes. Beyond it rests the frame pointer, followed by the saved return address.");
    say("Overflow the buffer into the frame pointer, and replace the return address with the hidden function.");
    say_pointer("The crystal ball reveals the hidden function at %p.", (void *)hidden_hutch);
    say("Sam: Addresses must be written least-significant byte first. In Python: import struct; struct.pack(\"<Q\", address).");
    printf("Inscribe the return path: ");
    read_inscription(steps);
}

int main(void) {
    setup();
    follow_trail();
    say("Sam: The untouched return address carries execution along its planned path.");
    return 0;
}
