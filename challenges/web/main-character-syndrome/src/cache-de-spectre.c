/* Cache de Spectre preview build. This self-contained ELF uses only the jail's
 * read/write/exit syscalls; players may submit their own binary instead. */
static long call(long number, long a, long b, long c) {
    long result;
    __asm__ volatile("syscall" : "=a"(result) : "a"(number), "D"(a), "S"(b), "d"(c)
                     : "rcx", "r11", "memory");
    return result;
}

void _start(void) {
    static const char message[] = "Old Town cache-de-spectre: preview complete\n";
    call(1, 1, (long)message, sizeof(message) - 1);
    call(60, 0, 0, 0);
    __builtin_unreachable();
}
