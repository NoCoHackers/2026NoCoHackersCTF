#include <stdio.h>

#include "common.h"

int main(void) {
    char story[128];
    int target = 0;

    setup();
    say("Sam: This lesson follows a different path: a format-string vulnerability, not another buffer overflow.");
    say("printf receives your input as its format string, so it processes every format specifier you provide.");
    say("Argument 1 is the character A. Argument 2 is an int pointer to the target.");
    say("The %n conversion writes the number of characters printed so far through the selected int pointer. Make the target equal 0x1337.");
    printf("Format string: ");
    if (fgets(story, sizeof(story), stdin) == NULL) {
        return 1;
    }
    printf(story, 'A', &target);

    if (target == 0x1337) {
        say("Sam: Excellent! Your format string used %n to write the required value through the target pointer.");
        say("Safe code uses printf(\"%s\", story), so player input remains data instead of becoming the format string.");
        print_flag("/flag/painted-sign.txt");
        return 0;
    }
    char response[96];
    snprintf(response, sizeof(response), "Sam: The target contains %#x, not 0x1337. Adjust your format string.", target);
    say(response);
    return 0;
}
