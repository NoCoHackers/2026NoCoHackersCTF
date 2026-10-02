#ifndef SAM_COMMON_H
#define SAM_COMMON_H

#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

static void setup(void) {
    setvbuf(stdin, NULL, _IONBF, 0);
    setvbuf(stdout, NULL, _IONBF, 0);
}

static void say(const char *message) {
    const struct timespec pause = {.tv_sec = 0, .tv_nsec = 35000000};
    for (const char *character = message; *character != '\0'; character++) {
        putchar(*character);
        nanosleep(&pause, NULL);
    }
    putchar('\n');
}

static void say_pointer(const char *message, const void *pointer) {
    char line[160];
    snprintf(line, sizeof(line), message, pointer);
    say(line);
}

// Deliberately unsafe teaching primitive: consume one complete binary
// inscription, but never check whether it still fits in the destination.
static void read_inscription(char *destination) {
    for (;;) {
        char character;
        ssize_t count = read(STDIN_FILENO, &character, 1);
        if (count <= 0) {
            exit(0);
        }
        if (character == '\n' || character == '\r') {
            return;
        }
        *destination++ = character;
    }
}

static void print_flag(const char *path) {
    char flag[256];
    FILE *file = fopen(path, "r");
    if (file == NULL || fgets(flag, sizeof(flag), file) == NULL) {
        say("Sam: The flag reliquary is sealed by an unintended ward. Tell an organizer.");
        exit(1);
    }
    fclose(file);
    printf("%s", flag);
}

#endif
