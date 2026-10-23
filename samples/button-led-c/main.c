/* Zero Lab sample in C: the Button widget (GPIO17, active low) drives the LED widget (GPIO27).
 * Uses the kernel GPIO character device (uapi v2) directly, so no extra packages are needed. */
#include <fcntl.h>
#include <linux/gpio.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

static int request_line(int chip, unsigned offset, unsigned long long flags, const char *name)
{
    struct gpio_v2_line_request req;
    memset(&req, 0, sizeof req);
    req.offsets[0] = offset;
    req.num_lines = 1;
    req.config.flags = flags;
    strncpy(req.consumer, name, sizeof req.consumer - 1);
    if (ioctl(chip, GPIO_V2_GET_LINE_IOCTL, &req) < 0) {
        perror(name);
        return -1;
    }
    return req.fd;
}

int main(void)
{
    int chip = open("/dev/gpiochip0", O_RDWR);
    if (chip < 0) {
        perror("/dev/gpiochip0");
        return 1;
    }
    int button = request_line(chip, 17, GPIO_V2_LINE_FLAG_INPUT, "zero-lab-button");
    int led = request_line(chip, 27, GPIO_V2_LINE_FLAG_OUTPUT, "zero-lab-led");
    if (button < 0 || led < 0)
        return 1;
    printf("Ready: press the Button widget (GPIO17); the LED widget (GPIO27) follows.\n");
    fflush(stdout);
    int last = -1;
    for (;;) {
        struct gpio_v2_line_values v = { .mask = 1 };
        if (ioctl(button, GPIO_V2_LINE_GET_VALUES_IOCTL, &v) < 0) {
            perror("read button");
            return 1;
        }
        int pressed = !(v.bits & 1); /* active low */
        if (pressed != last) {
            struct gpio_v2_line_values out = { .mask = 1, .bits = (unsigned long long)pressed };
            ioctl(led, GPIO_V2_LINE_SET_VALUES_IOCTL, &out);
            printf("%s\n", pressed ? "pressed" : "released");
            fflush(stdout);
            last = pressed;
        }
        usleep(10000);
    }
}
