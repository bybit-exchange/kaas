//go:build windows

package bridge

import (
	"os"
	"os/exec"
	"strconv"
)

// setKillTree force-kills the child and its descendants when the command's
// context is cancelled. Windows has no process groups, so taskkill /T walks
// the tree instead; if it fails (e.g. the process already exited), signalling
// the direct child reports os.ErrProcessDone, which Wait ignores.
func setKillTree(cmd *exec.Cmd) {
	cmd.Cancel = func() error {
		kill := exec.Command("taskkill", "/T", "/F", "/PID", strconv.Itoa(cmd.Process.Pid))
		if err := kill.Run(); err != nil {
			return cmd.Process.Signal(os.Kill)
		}
		return nil
	}
}
