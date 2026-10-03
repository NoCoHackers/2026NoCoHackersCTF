/*
 * old town accounts - night ledger
 */
char cmd[64];
char buf[256];

main()
{
        printf("\nOLD TOWN ACCOUNTS\n");
        printf("night clerk station\n");
        night();
        for (;;) {
                printf("\n1  account inquiry\n");
                printf("2  journal entries\n");
                printf("3  reconcile batch\n");
                printf("4  print report\n");
                printf("5  operator notices\n");
                printf("6  sign off\n");
                printf("selection: ");
                if (rdline() == 0)
                        exit();
                switch (buf[0]) {
                case '1':
                        inquiry();
                        break;
                case '2':
                        journal();
                        break;
                case '3':
                        night();
                        break;
                case '4':
                        reports();
                        break;
                case '5':
                        notices();
                        break;
                case '6':
                        exit();
                default:
                        printf("?\n");
                }
        }
}

night()
{
        printf("\nNIGHTLY BALANCE REPORT - Oct 30 1974\n\n");
        pfile("/usr/ledger/night.rpt");
}

pfile(name)
char *name;
{
        int f, n;
        char b[512];
        f = open(name, 0);
        if (f < 0) {
                printf("(cannot read %s)\n", name);
                return;
        }
        while ((n = read(f, b, 512)) > 0)
                write(1, b, n);
        close(f);
}

ask(p)
char *p;
{
        printf("%s", p);
        if (rdline() == 0)
                exit();
        trim();
}

rdline()
{
        int c, i;
        i = 0;
        while ((c = getchar()) != '\n') {
                if (c <= 0)
                        return 0;
                if (i < 250)
                        buf[i++] = c;
        }
        buf[i] = '\0';
        return 1;
}

trim()
{
        int i;
        for (i = 0; buf[i]; i++)
                ;
        while (i > 0 && (buf[i-1] == ' ' || buf[i-1] == '\n'))
                i--;
        buf[i] = '\0';
}

streq(s)
char *s;
{
        int i;
        for (i = 0; s[i]; i++)
                if (buf[i] != s[i])
                        return 0;
        if (buf[i] == '\0')
                return 1;
        return 0;
}

copy(a, b)
char *a, *b;
{
        int i;
        for (i = 0; b[i]; i++)
                a[i] = b[i];
        a[i] = '\0';
}

inquiry()
{
        printf("\nACCOUNT INQUIRY\n\n");
        pfile("/usr/ledger/accounts");
        ask("\naccount number: ");
        if (streq("0317"))
                printf("0317  night payments  NO HOLDER ON FILE\nbalance: see operator.\n");
        else
                printf("no such account at this station.\n");
}

journal()
{
        printf("\nJOURNAL - night of Oct 30 1974\n\n");
        pfile("/usr/ledger/journal");
        ask("\nreprint entry no: ");
        if (!streq("1041")) {
                printf("entry not available for reprint.\n");
                return;
        }
        ask("report type [M]: ");
        if (buf[0] == '\0')
                copy(cmd, "M");
        else
                copy(cmd, buf);
        reprint(cmd);
}

reprint(type)
char *type;
{
        int i;
        printf("(reprinting via legacy report processor)\n");
        if (fork() == 0) {
                execl("/bin/sh", "sh", "/usr/ledger/report", type, 0);
                printf("cannot run report processor.\n");
                exit();
        }
        wait(&i);
}

reports()
{
        printf("\nREPORTS AT THIS STATION\n");
        printf("  N  nightly balance\n");
        printf("  R  rent roll\n");
        printf("  I  income summary\n");
        ask("type: ");
        if (streq("N")) {
                night();
                return;
        }
        if (streq("R")) {
                pfile("/usr/ledger/rentroll");
                return;
        }
        if (streq("I")) {
                pfile("/usr/ledger/income");
                return;
        }
        printf("unknown report type at this station.\n");
        printf("see operator notices regarding retired designations.\n");
}

notices()
{
        printf("\nOPERATOR NOTICES\n\n");
        pfile("/usr/ledger/notices");
        ask("\nreference no: ");
        if (streq("7")) {
                pfile("/usr/ledger/bulletin7");
                return;
        }
        printf("no such reference at this station.\n");
}
