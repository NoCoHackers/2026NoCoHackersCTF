/* A syscall-only runner for uploaded x86-64 ELF programs. The outer Docker
 * container retains read-only rootfs, no capabilities, and no new privileges. */
#define _GNU_SOURCE
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

#define ALLOW(n) \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (n), 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)

int main(int argc, char **argv) {
    if (argc != 2) return 1;
    int fd = atoi(argv[1]);
    if (fd < 3 || fcntl(fd, F_SETFD, FD_CLOEXEC) < 0) return 1;
    struct sock_filter rules[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        ALLOW(__NR_read),
        ALLOW(__NR_write),
        ALLOW(__NR_exit),
        ALLOW(__NR_exit_group),
        ALLOW(__NR_rt_sigreturn),
        ALLOW(__NR_execveat),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
    };
    struct sock_fprog filter = {
        .len = (unsigned short)(sizeof(rules) / sizeof(rules[0])),
        .filter = rules,
    };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0 ||
        prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &filter) < 0) {
        perror("jail: seccomp unavailable");
        return 1;
    }
    char *env[] = {NULL};
    char *args[] = {(char *)"candidate", NULL};
    /* /tmp is deliberately noexec. Execute the verified upload from a memfd
       instead of loosening the container's mount restrictions. */
    syscall(__NR_execveat, fd, "", args, env, AT_EMPTY_PATH);
    write(2, "jail: exec failed\n", 18);
    return 1;
}
