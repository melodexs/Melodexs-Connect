function isValidNigerianPhone(phone) {
    return /^0[7-9][0-1][0-9]{8}$/.test(String(phone || ""));
}

module.exports = {
    isValidNigerianPhone
};
