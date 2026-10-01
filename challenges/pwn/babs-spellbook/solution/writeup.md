# Babs's Spellbook - author's write-up

**Flags:** declared in the five manifests under `challenges/pwn/babs-spellbook/`
(`challenge.yml` plus `challenge.<id>.yml` for lessons 2-5).

One TCP service, five independently scored SQLite lessons. Every connection
gets a fresh in-memory database, so there is no player state to reset and no
way to interfere with another player. Connect, pick a lesson number, and Babs
the cat-witch shows you the exact query she is about to cast - the challenge
is always to understand the query you are given, never to guess a filter.

The progression teaches the standard SQL injection ladder, one rung at a time:
authentication bypass, UNION extraction, schema discovery, blind boolean
inference, and finally second-order injection. After each flag, Babs shows the
corresponding parameterized Go query; lesson 5 shows that both writes and later
reads must bind untrusted values.

## Lesson 1 - The Familiar's Gate (authentication bypass)

Babs shows her gate spell:

```sql
SELECT name FROM apprentices WHERE name = '<name>' AND secret = '<secret>'
```

Intended answer: `name = ' OR 1=1 --` with any secret. The injected quote
closes the string, `OR 1=1` is always true, and `--` comments out the rest of
the line - including the entire secret check, because the query is one line.
The player learns the core idea: unescaped input crosses from *data* into
*query structure*. Alternatives like `babs' --` (quote + comment only) work
too and make a nice hint for anyone stuck.

Flag file: `/flag/flag.txt` (primary).

## Lesson 2 - The Misfiled Spellbook (UNION extraction)

The catalogue shows two columns and searches by title:

```sql
SELECT title, description FROM spells WHERE title LIKE '%<search>%'
```

Intended answer: `' UNION SELECT title, description FROM locked_shelf --`.
The locked shelf has the same two columns, so the UNION appends its row to
the result set and the challenge helpfully prints it. The lesson is that a
SELECT's result set is shaped by the query, not by the author's intent, and
that column counts must match for UNION.

Flag file: `/flag/misfiled-spellbook.txt`.

## Lesson 3 - Names Have Power (schema discovery)

The flag sits in a hidden table whose name the player does not know. The
search is repeatable within one connection (up to eight casts), which matters:
the database is per-connection, so discovery and extraction must share a
session.

Cast 1 asks SQLite to describe itself:

```sql
' UNION SELECT name, sql FROM sqlite_master --
```

`sqlite_master` lists every table and its `CREATE TABLE` statement, revealing
`moonlit_reliquary(incantation, ember)`. Cast 2 borrows the discovered
table's columns:

```sql
' UNION SELECT * FROM moonlit_reliquary --
```

(`SELECT *` works because the lesson guarantees a two-column table; spelling
out `incantation, ember` is the general form.) The lesson is that the schema
is itself data, and discovery comes before extraction.

Flag file: `/flag/names-have-power.txt`.

## Lesson 4 - The Silent Oracle (blind boolean inference)

The oracle prints exactly one bit per cast - nod or shake - and gives no
errors and no rows:

```sql
SELECT 1 FROM omens WHERE word = '<guess>'
```

Injecting a comparison turns that bit into a predicate:

```sql
x' OR substr(word,1,1) > 'm
```

(assembles to `word = 'x' OR substr(word,1,1) > 'm'` - the template's closing
quote finishes the probe). Binary-searching each position takes at most five
casts per letter, about twenty for the four-letter word, well inside the
oracle's eighty-cast patience. Once the word is known, `!claim <word>` speaks
the flag; the solve script re-verifies with `x' OR word = '<word>` before
claiming. The lesson: a single observable bit leaks everything, given enough
questions.

Flag file: `/flag/silent-oracle.txt`.

## Lesson 5 - The Remembering Cauldron (second-order injection)

Storing the recipe name uses a bound parameter, so the poison is saved as data.
The bug is later, when the cauldron interpolates that stored name into its
retrieval query:

```sql
SELECT ingredient FROM recipes WHERE name = '<stored name>'
```

Intended answer: store `x' UNION SELECT ingredient FROM sealed_vial --`,
then say `retrieve` when prompted. The lesson: parameterized writes do not make
stored data safe to interpolate elsewhere - the fix belongs at *every* place
the data meets a query, and stored data must be treated as untrusted input
forever.

Flag file: `/flag/remembering-cauldron.txt`.

## Difficulty

A five-rung ladder from beginner to intermediate. Lessons 1-2 are solvable in
minutes by anyone who has read a SQL injection primer; lesson 3 adds the
`sqlite_master` step; lesson 4 is the first real jump (inference, scripting
the oracle); lesson 5 rewards players who read the application's behavior
instead of pattern-matching a quote. Because each lesson is its own flag,
nobody is blocked by a hard rung - they can take the earlier points and come
back.

## Organizer notes

- One container, `nc chal.nocohackers.com 30002`. socat forks a fresh process
  per connection; the database is `:memory:` inside it, so there is no state
  to reset between players and no shared data to corrupt.
- Each lesson prints only its own flag, and only its own flag file is opened,
  so an early lesson can never leak a later one.
- The service is Go with a CGO-backed SQLite driver. Resources are 96 MB /
  0.5 CPU; each connection is short-lived, `CHAL_TIMEOUT` reaps idlers.
- If it dies: `make -C deploy/chals restart S=pwn-babs-spellbook` on the
  challenge host.
- The autosolves are the intended paths, verbatim: stage 3 parses
  `sqlite_master` for the table name before its second cast, and stage 4
  genuinely binary-searches the oracle's word before claiming it.
