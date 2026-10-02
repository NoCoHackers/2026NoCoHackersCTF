#include <stdio.h>
#include <string.h>

#include "common.h"

int main(void) {
    struct {
        char name[16];
        unsigned int carrots;
    } burrow = {{0}, 0};

    setup();
    say("Sam: Young apprentice, the Burrow names every guest and weighs their offering.");
    say("Its name stone holds 16 bytes, with the carrot tally etched beside it. Can one inscription spill into the next?");
    printf("Name: ");
    fgets(burrow.name, 64, stdin);

    if (burrow.carrots == 10) {
        say("Sam: Nice spell! Your overflowing inscription enchanted the neighboring tally marks.");
        say("A safe sorcerrer passes sizeof burrow.name to fgets, so the name won't overflow into the neighboring data structure.");
        print_flag("/flag/flag.txt");
        return 0;
    }
    char response[96];
    snprintf(response, sizeof(response), "Sam: The ward senses %u carrots. Ten are required to break the seal.", burrow.carrots);
    say(response);
    return 0;
}
