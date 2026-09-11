//go:build unix

package bridge

import (
	"os"
	"os/exec"
	"syscall"
)

// setKillTree puts the child in its own process group so a context
// cancellation can SIGKILL the whole group, taking down the daemon's own
// children (uv spawns the Python process) along with it.
func setKillTree(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	cmd.Cancel = func() error {
		if killErr := syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL); killErr == syscall.ESRCH {
			return os.ErrProcessDone
		} else { //nolint:revive
			return killErr
		}
	}
}
