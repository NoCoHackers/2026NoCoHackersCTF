/* An approved release job can read one input stream and report its contents. */
static long call(long number, long a, long b, long c) {
    long result;
    __asm__ volatile("syscall" : "=a"(result) : "a"(number), "D"(a), "S"(b), "d"(c)
                     : "rcx", "r11", "memory");
    return result;
}

void _start(void) {
    char buffer[128];
    long length = call(0, 0, (long)buffer, sizeof(buffer));
    if (length > 0) call(1, 1, (long)buffer, length);
    call(60, 0, 0, 0);
    __builtin_unreachable();
}
