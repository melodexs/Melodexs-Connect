function isValidNigerianPhone(phone) {
    return /^0[7-9][0-1][0-9]{8}$/.test(phone);
}

module.exports = {
    isValidNigerianPhone
};
