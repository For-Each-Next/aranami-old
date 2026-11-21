/** Display grouped measurements with a thin space and a decimal point. */
const whole = new Intl.NumberFormat("en-US", {maximumFractionDigits: 0});
const tenths = new Intl.NumberFormat("en-US", {minimumFractionDigits: 1, maximumFractionDigits: 1});

export function groupedNumber(value, decimal = false) {
    return (decimal ? tenths : whole).format(value).replaceAll(",", "\u2009");
}
