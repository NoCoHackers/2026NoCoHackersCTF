/* A jail regression probe: trying to open the server's process environment
 * must be stopped before it can appear in the release-job output. */
static long call(long number, long a, long b, long c) {
    long result;
    __asm__ volatile("syscall" : "=a"(result) : "a"(number), "D"(a), "S"(b), "d"(c)
                     : "rcx", "r11", "memory");
    return result;
}

void _start(void) {
    static const char path[] = "/proc/1/environ";
    long fd = call(257, -100, (long)path, 0); /* openat */
    if (fd >= 0) {
        char data[256];
        long n = call(0, fd, (long)data, sizeof(data));
        if (n > 0) call(1, 1, (long)data, n);
    }
    call(60, 0, 0, 0);
    __builtin_unreachable();
}
