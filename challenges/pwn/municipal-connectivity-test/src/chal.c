#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define INPUT_SIZE 512
#define COMMAND_SIZE (INPUT_SIZE + 16)

int main(void)
{
    char input[INPUT_SIZE];
    char command[COMMAND_SIZE];

    setvbuf(stdout, NULL, _IONBF, 0);
    puts("Welcome to the municipal internet connectivity test server, all messages received are sent back to the sender verbatim");

    if (fgets(input, sizeof(input), stdin) == NULL) {
        return 0;
    }
    input[strcspn(input, "\r\n")] = '\0';

    /* The old test utility delegates its echo to the system shell. */
    if (snprintf(command, sizeof(command), "echo %s", input) < 0) {
        return 1;
    }

    return system(command) == -1;
}
