/* Minimal newlib stubs: this firmware does no file I/O. Defining them here keeps
 * the link free of "not implemented" warnings from libc_nano. */
#include <errno.h>
#include <sys/stat.h>

int _close(int fd)                      { (void)fd; errno = EBADF; return -1; }
int _lseek(int fd, int off, int whence) { (void)fd; (void)off; (void)whence; errno = ESPIPE; return -1; }
int _read(int fd, char *p, int n)       { (void)fd; (void)p; (void)n; errno = EBADF; return -1; }
int _write(int fd, char *p, int n)      { (void)fd; (void)p; (void)n; errno = EBADF; return -1; }
int _fstat(int fd, struct stat *st)     { (void)fd; st->st_mode = S_IFCHR; return 0; }
int _isatty(int fd)                     { (void)fd; return 1; }
