// Babs's deliberately vulnerable, per-connection SQLite lessons.
package main

import (
	"bufio"
	"database/sql"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	_ "github.com/mattn/go-sqlite3"
)

type lesson struct {
	in  *bufio.Reader
	out *bufio.Writer
}

func (l *lesson) say(message string, spoken bool) {
	if spoken {
		// Only Babs's spoken dialogue is paced; prompts, query examples, and
		// flags stay immediate so players and scripted solves can respond.
		for _, character := range message {
			fmt.Fprint(l.out, string(character))
			l.out.Flush()
			time.Sleep(50 * time.Millisecond)
		}
		fmt.Fprintln(l.out)
		l.out.Flush()
		return
	}
	fmt.Fprintln(l.out, message)
	l.out.Flush()
}

func (l *lesson) ask(prompt string) (string, error) {
	fmt.Fprint(l.out, prompt, " ")
	l.out.Flush()
	line, err := l.in.ReadString('\n')
	if err != nil && err != io.EOF {
		return "", err
	}
	if len(line) == 0 {
		return "", io.EOF
	}
	// The PTY does not echo input; finish the prompt line before replying.
	fmt.Fprintln(l.out)
	l.out.Flush()
	return strings.TrimRight(strings.TrimSuffix(line[:min(len(line), 513)], "\n"), "\r"), nil
}

func flag(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		panic(err)
	}
	return strings.TrimSpace(string(data))
}

func database() *sql.DB {
	// socat forks a fresh process per player; :memory: also isolates lessons.
	db, err := sql.Open("sqlite3", ":memory:")
	if err != nil {
		panic(err)
	}
	db.SetMaxOpenConns(1)
	return db
}

func setup(db *sql.DB, query string, args ...any) {
	if _, err := db.Exec(query, args...); err != nil {
		panic(err)
	}
}

func (l *lesson) rows(db *sql.DB, query string) [][]string {
	result, err := db.Query(query)
	if err != nil {
		l.say("The query fizzles: "+err.Error(), false)
		return nil
	}
	defer result.Close()
	columns, err := result.Columns()
	if err != nil {
		panic(err)
	}
	var all [][]string
	for result.Next() {
		values := make([]sql.NullString, len(columns))
		pointers := make([]any, len(columns))
		for i := range values {
			pointers[i] = &values[i]
		}
		if err := result.Scan(pointers...); err != nil {
			panic(err)
		}
		row := make([]string, len(columns))
		for i, value := range values {
			row[i] = value.String
		}
		all = append(all, row)
		if len(all) == 20 {
			break
		}
	}
	if err := result.Err(); err != nil {
		panic(err)
	}
	return all
}

func (l *lesson) gate() error {
	l.say(`Babs: My young apprentice, this gate checks both a name and a secret before it will open. The programmer copies your answers directly into its query instead of binding them in a parameter. If your name changes the query, the secret may not matter.`, true)
	l.say("The query: SELECT name FROM apprentices WHERE name = '<name>' AND secret = '<secret>'", false)
	db := database()
	defer db.Close()
	setup(db, "CREATE TABLE apprentices(name TEXT, secret TEXT)")
	setup(db, "INSERT INTO apprentices VALUES (?, ?)", "babs", "moon-milk")
	for {
		name, err := l.ask("Name:")
		if err != nil {
			return err
		}
		secret, err := l.ask("Secret:")
		if err != nil {
			return err
		}
		result := l.rows(db, fmt.Sprintf("SELECT name FROM apprentices WHERE name = '%s' AND secret = '%s'", name, secret))
		if len(result) > 0 {
			l.say("Babs: Well done, padawan. You're in.", true)
			l.say(flag("/flag/flag.txt"), false)
			l.say("Babs: Bind each answer as data, not spellcraft:", true)
			l.say(`Safer query: db.Query("SELECT name FROM apprentices WHERE name = ? AND secret = ?", name, secret)`, false)
			l.say("The question marks hold values; quotes in a name cannot change the query.", false)
			return nil
		}
		l.say("Babs: The door remains shut. Try again, padawan.", true)
	}
}

func (l *lesson) catalogue() error {
	l.say(`Babs: My young apprentice, this catalogue searches public spells by title. Each result shows a title and a description, but my locked shelf holds ancient forbidden spells. Your search text is again copied directly into the query. Could a UNION join them?`, true)
	l.say("The query: SELECT title, description FROM spells WHERE title LIKE '%<search>%'", false)
	db := database()
	defer db.Close()
	setup(db, "CREATE TABLE spells(title TEXT, description TEXT)")
	setup(db, "INSERT INTO spells VALUES ('Lantern', 'A little light')")
	setup(db, "CREATE TABLE locked_shelf(title TEXT, description TEXT)")
	setup(db, "INSERT INTO locked_shelf VALUES (?, ?)", "The sealed page", flag("/flag/misfiled-spellbook.txt"))
	for {
		term, err := l.ask("Search title:")
		if err != nil {
			return err
		}
		result := l.rows(db, fmt.Sprintf("SELECT title, description FROM spells WHERE title LIKE '%%%s%%'", term))
		for _, row := range result {
			l.say(row[0]+" | "+row[1], false)
			if row[1] == flag("/flag/misfiled-spellbook.txt") {
				l.say("Babs: A bound search stays within its intended query:", true)
				l.say(`Safer query: db.Query("SELECT title, description FROM spells WHERE title LIKE ?", "%"+term+"%")`, false)
				l.say("The wildcards are part of the value, not pasted into SQL.", false)
				return nil
			}
		}
		if len(result) == 0 {
			l.say("Babs: No pages found. Try another search.", true)
		}
	}
}

func (l *lesson) names() error {
	l.say(`Babs: My young apprentice, these index cards do not contain the hidden page. Nor do I tell you which table holds it. SQLite may have a special place where it records its own table names and columns. Ask it what tables exist first; then search the one you discover.`, true)
	l.say("The query: SELECT title, note FROM index_cards WHERE title LIKE '%<search>%'", false)
	db := database()
	defer db.Close()
	setup(db, "CREATE TABLE index_cards(title TEXT, note TEXT)")
	setup(db, "INSERT INTO index_cards VALUES ('Candle', 'Find the secret table first')")
	setup(db, "CREATE TABLE moonlit_reliquary(incantation TEXT, ember TEXT)")
	setup(db, "INSERT INTO moonlit_reliquary VALUES (?, ?)", "final verse", flag("/flag/names-have-power.txt"))
	// Multiple casts allow discovery, failed attempts, and extraction within one connection.
	for {
		term, err := l.ask("Search index cards (blank to leave):")
		if err != nil {
			return err
		}
		if term == "" {
			break
		}
		result := l.rows(db, fmt.Sprintf("SELECT title, note FROM index_cards WHERE title LIKE '%%%s%%'", term))
		for _, row := range result {
			l.say(row[0]+" | "+row[1], false)
			if row[1] == flag("/flag/names-have-power.txt") {
				l.say("Babs: A bound search cannot ask the spellbook about other tables:", true)
				l.say(`Safer query: db.Query("SELECT title, note FROM index_cards WHERE title LIKE ?", "%"+term+"%")`, false)
				l.say("Keep secret tables in a separate database when they need stronger isolation.", false)
				return nil
			}
		}
		if len(result) == 0 {
			l.say("Babs: No pages found.", true)
		}
	}
	return nil
}

func (l *lesson) oracle() error {
	l.say(`Babs: My young apprentice, the oracle guards a four-letter word. It checks your guess with a query, but reveals only a nod or a shake. Your words are copied into that query. Ask questions it can answer to retrieve the word.`, true)
	l.say("The query: SELECT 1 FROM omens WHERE word = '<guess>'", false)
	db := database()
	defer db.Close()
	setup(db, "CREATE TABLE omens(word TEXT)")
	setup(db, "INSERT INTO omens VALUES ('moth')")
	for {
		guess, err := l.ask("Ask oracle (or !claim WORD):")
		if err != nil {
			return err
		}
		if strings.HasPrefix(guess, "!claim ") {
			if guess[7:] == "moth" {
				l.say("Babs: The oracle bows.", true)
				l.say(flag("/flag/silent-oracle.txt"), false)
				l.say("Babs: Even a yes-or-no query must bind its question:", true)
				l.say(`Safer query: var found int; err := db.QueryRow("SELECT 1 FROM omens WHERE word = ?", guess).Scan(&found)`, false)
				l.say("No match gives sql.ErrNoRows; an injected comparison is only a string.", false)
				return nil
			}
			l.say("Babs: That is not its word. Try again, padawan.", true)
			continue
		}
		// Errors and misses are intentionally indistinguishable to the player.
		result, err := db.Query(fmt.Sprintf("SELECT 1 FROM omens WHERE word = '%s'", guess))
		if err != nil {
			l.say("The oracle shakes its head.", true)
			continue
		}
		found := result.Next()
		result.Close()
		if found {
			l.say("The oracle nods.", true)
		} else {
			l.say("The oracle shakes its head.", true)
		}
	}
	return nil
}

func (l *lesson) cauldron() error {
	l.say(`Babs: My young apprentice, I write every recipe name into my ledger without changing a single word. Safe enough, yes? But when you ask me to fetch it, my old lookup copies that name into the query itself. A troublesome name might become more than a name.`, true)
	l.say("The query: SELECT ingredient FROM recipes WHERE name = '<stored name>'", false)
	db := database()
	defer db.Close()
	setup(db, "CREATE TABLE recipes(name TEXT, ingredient TEXT)")
	setup(db, "INSERT INTO recipes VALUES ('tea', 'mint')")
	setup(db, "CREATE TABLE sealed_vial(ingredient TEXT)")
	setup(db, "INSERT INTO sealed_vial VALUES (?)", flag("/flag/remembering-cauldron.txt"))
	for {
		name, err := l.ask("Store a recipe name:")
		if err != nil {
			return err
		}
		setup(db, "INSERT INTO recipes VALUES (?, ?)", name, "stardust")
		l.say("Babs: The name is stored. Type retrieve to use my old lookup.", true)
		command, err := l.ask("Retrieve that recipe:")
		if err != nil {
			return err
		}
		if strings.ToLower(command) != "retrieve" {
			l.say("Babs: Nothing was retrieved. Try another recipe.", true)
			continue
		}
		result := l.rows(db, fmt.Sprintf("SELECT ingredient FROM recipes WHERE name = '%s'", name))
		for _, row := range result {
			l.say("Ingredient: "+row[0], false)
			if row[0] == flag("/flag/remembering-cauldron.txt") {
				l.say("Babs: Storage was safe, but retrieval needed a binding too:", true)
				l.say(`Safer query (write): db.Exec("INSERT INTO recipes VALUES (?, ?)", name, "stardust")`, false)
				l.say(`Safer query (read): db.Query("SELECT ingredient FROM recipes WHERE name = ?", name)`, false)
				l.say("Treat stored names as untrusted data every time you use them.", false)
				return nil
			}
		}
		if len(result) == 0 {
			l.say("Babs: The cauldron is empty. Try another recipe.", true)
		}
	}
}

func main() {
	l := &lesson{in: bufio.NewReader(os.Stdin), out: bufio.NewWriter(os.Stdout)}
	l.say("  /\\_/\\ ", false)
	l.say(" ( o.o )  Ancient database magic awaits, padawan.", false)
	l.say("  > ^ <   1 Gate | 2 Spellbook | 3 Names | 4 Oracle | 5 Cauldron", false)
	l.say("Each lesson has its own sealed spellbook. Choose a number:", false)
	for {
		choice, err := l.ask("Lesson:")
		if err != nil {
			return
		}
		switch choice {
		case "1":
			err = l.gate()
		case "2":
			err = l.catalogue()
		case "3":
			err = l.names()
		case "4":
			err = l.oracle()
		case "5":
			err = l.cauldron()
		default:
			l.say("Babs: Choose a lesson from 1 to 5, padawan.", true)
			continue
		}
		if err != nil {
			return // A disconnected apprentice needs no further output.
		}
		l.say("  > ^ <   1 Gate | 2 Spellbook | 3 Names | 4 Oracle | 5 Cauldron", false)
	}
}
