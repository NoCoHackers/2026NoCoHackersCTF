// Boone's deliberately vulnerable, per-connection shell lessons.
package main

import (
	"bufio"
	"bytes"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"
)

type lesson struct {
	in  *bufio.Reader
	out *bufio.Writer
}

func (l *lesson) say(message string, spoken bool) {
	if spoken {
		for _, character := range message {
			fmt.Fprint(l.out, string(character))
			l.out.Flush()
			time.Sleep(35 * time.Millisecond)
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

func shell(command string) (string, bool) {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, "/bin/sh", "-c", command)
	cmd.Env = []string{"PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/tmp"}
	var output bytes.Buffer
	cmd.Stdout = &output
	cmd.Stderr = &output
	err := cmd.Run()
	return output.String(), err == nil
}

func safeOutput(output string) string {
	var kept []string
	for _, line := range strings.Split(strings.TrimSpace(output), "\n") {
		// Bundle flags share the container. A lesson only awards its own flag;
		// direct attempts to dump /flag never disclose neighboring answers.
		if strings.Contains(line, "noco{") || strings.Contains(line, "/flag/") {
			continue
		}
		if line != "" {
			kept = append(kept, line)
		}
	}
	return strings.Join(kept, "\n")
}

func hasExactLine(output, marker string) bool {
	for _, line := range strings.Split(strings.TrimSpace(output), "\n") {
		if strings.TrimSuffix(line, "\r") == marker {
			return true
		}
	}
	return false
}

func (l *lesson) visible(command, marker, flagPath string) bool {
	output, _ := shell(command)
	if hasExactLine(output, marker) {
		l.say("Boone: Arf! You found the hidden trail.", true)
		l.say(flag(flagPath), false)
		return true
	}
	if clean := safeOutput(output); clean != "" {
		l.say(clean, false)
	} else {
		l.say("Boone sniffs around, but finds nothing.", true)
	}
	return false
}

func (l *lesson) scentBook() error {
	l.say("Boone: This scent search wraps your text in single quotes before passing it to grep. Break out of the quote, add another command, and comment out the tail. Make it print BOONE_FOUND_1.", true)
	l.say("The command: grep -i '<scent>' /srv/trails/scents.txt", false)
	for {
		scent, err := l.ask("Scent:")
		if err != nil {
			return err
		}
		if l.visible("grep -i '"+scent+"' /srv/trails/scents.txt", "BOONE_FOUND_1", "/flag/flag.txt") {
			l.say("Safer Go: exec.Command(\"grep\", \"-i\", \"--\", scent, \"/srv/trails/scents.txt\")", false)
			l.say("Direct arguments prevent shell syntax; -- also ends grep option parsing.", false)
			return nil
		}
	}
}

func (l *lesson) fetchOptions() error {
	l.say("Boone: This trail-packaging tool runs GNU tar directly without a shell, but it still accepts your text as a tar option. Some programs have dangerous options that execute commands. Supply one option that makes tar print BOONE_FOUND_2.", true)
	l.say("The argv: tar --checkpoint=1 <your option> -cf /tmp/trail-pack.tar /srv/trails/scents.txt", false)
	for {
		option, err := l.ask("Tar option:")
		if err != nil {
			return err
		}
		ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		cmd := exec.CommandContext(ctx, "tar", "--checkpoint=1", option, "-cf", fmt.Sprintf("/tmp/trail-pack-%d.tar", os.Getpid()), "/srv/trails/scents.txt")
		cmd.Env = []string{"PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/tmp"}
		output, _ := cmd.CombinedOutput()
		cancel()
		if hasExactLine(string(output), "BOONE_FOUND_2") {
			l.say("Boone: Arf! The option changed what the program did.", true)
			l.say(flag("/flag/dangerous-options.txt"), false)
			l.say("Safer Go: reject option-like values, add -- before filenames, and allowlist expected argument forms.", false)
			l.say("Skipping the shell prevents shell syntax, but it does not make every program argument safe.", false)
			return nil
		}
		if clean := safeOutput(string(output)); clean != "" {
			l.say(clean, false)
		} else {
			l.say("Boone paws at the empty pack.", true)
		}
	}
}

func (l *lesson) whistle() error {
	l.say("Boone: This path check reveals no command output, only whether I sit or run. A four-letter whistle word is in /srv/trails/whistle. Change the command's exit status to ask yes-or-no questions, then claim it.", true)
	l.say("The command: test -d '/srv/trails/<path>'", false)
	for {
		probe, err := l.ask("Path probe (or !claim WORD):")
		if err != nil {
			return err
		}
		if strings.HasPrefix(probe, "!claim ") {
			if probe[7:] == "bark" {
				l.say("Boone sits and offers a paw.", true)
				l.say(flag("/flag/quiet-whistle.txt"), false)
				l.say("Safer Go: info, err := os.Stat(filepath.Join(root, path))", false)
				l.say("Validate the resolved path stays below root; never build a test command.", false)
				return nil
			}
			l.say("Boone tilts his head. That is not the whistle.", true)
			continue
		}
		_, ok := shell("test -d '/srv/trails/" + probe + "'")
		if ok {
			l.say("Boone sits.", true)
		} else {
			l.say("Boone runs ahead.", true)
		}
	}
}

func (l *lesson) rememberedRoute() error {
	l.say("Boone: I store your route name safely. Later, an old trail runner pastes it inside a double-quoted shell string. Quotes stop word splitting, but command substitution still runs. Make the later command print BOONE_FOUND_4 on its own line.", true)
	l.say("The later command: printf \"Following route: <stored route>\\n\"", false)
	for {
		route, err := l.ask("Store route name:")
		if err != nil {
			return err
		}
		routePath := fmt.Sprintf("/tmp/boone-route-%d", os.Getpid())
		if err := os.WriteFile(routePath, []byte(route), 0600); err != nil {
			return err
		}
		l.say("Boone queues it on disk. Type follow to let the old trail runner process the job.", true)
		action, err := l.ask("Action:")
		if err != nil {
			return err
		}
		if strings.ToLower(action) != "follow" {
			l.say("Boone stays put. Try another route.", true)
			continue
		}
		stored, err := os.ReadFile(routePath)
		if err != nil {
			return err
		}
		if l.visible("printf \"Following route: "+string(stored)+"\\n\"", "BOONE_FOUND_4", "/flag/old-dog-new-tricks.txt") {
			l.say("Safer Go: fmt.Fprintf(output, \"Following route: %s\\n\", route)", false)
			l.say("Double quotes are not a command-injection defense, and safe storage does not sanitize later use.", false)
			return nil
		}
	}
}

func main() {
	l := &lesson{in: bufio.NewReader(os.Stdin), out: bufio.NewWriter(os.Stdout)}
	l.say(" / \\__", false)
	l.say("(    @\\___  Boone's command-line trail school", false)
	l.say(" /         O", false)
	l.say("/   (_____/   1 Scents | 2 Options | 3 Whistle | 4 Old Route", false)
	l.say("/_____/   U", false)
	for {
		choice, err := l.ask("Lesson:")
		if err != nil {
			return
		}
		switch choice {
		case "1":
			err = l.scentBook()
		case "2":
			err = l.fetchOptions()
		case "3":
			err = l.whistle()
		case "4":
			err = l.rememberedRoute()
		default:
			l.say("Boone: Woof! Choose a lesson from 1 to 4.", true)
			continue
		}
		if err != nil {
			return
		}
		l.say("1 Scents | 2 Options | 3 Whistle | 4 Old Route", false)
	}
}
