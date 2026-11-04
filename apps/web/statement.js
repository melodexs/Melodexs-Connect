/* Wallet statement export (CSV).
 *
 * Pure functions, no DOM and no network, so the same code is unit-tested in
 * Node and used by the Wallet page. The page feeds it the user's own
 * transactions, fetched through the existing ownership-checked endpoint.
 */
(function (root) {
    "use strict";

    var COLUMNS = ["Date", "Reference", "Type", "Description", "Amount (NGN)", "Direction", "Status"];

    // A cell that starts with = + - @ (or a tab/CR) is executed as a formula by
    // Excel and Google Sheets. Descriptions can include supplier text, so prefix
    // such cells with an apostrophe to force them to be read as plain text.
    function neutralise(text) {
        return /^[=+\-@\t\r]/.test(text) ? "'" + text : text;
    }

    function cell(value) {
        var text = neutralise(value == null ? "" : String(value));
        return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
    }

    function isoDate(value) {
        var d = new Date(value);
        if (isNaN(d.getTime())) return "";
        function p(n) { return n < 10 ? "0" + n : "" + n; }
        return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
    }

    function describeType(t) {
        return t.type === "wallet_funding" || t.type === "credit" ? "Wallet funding" : "Purchase";
    }

    // Stored descriptions look like
    //   "MTN 1GB WEEKLY data purchase for 0803... | Category: Weekly | ISQUAREDATA confirmed ..."
    // Only the first segment is written for the customer. Everything after the
    // first " | " is internal bookkeeping (supplier names, reconciliation notes),
    // which must not appear on a customer's screen, receipt or statement.
    function customerDescription(text) {
        if (text == null) return "";
        return String(text).split(" | ")[0].trim();
    }

    function row(t) {
        var credit = t.type === "wallet_funding" || t.type === "credit";
        var amount = Number(t.amount);
        return [
            isoDate(t.created_at),
            t.reference || "",
            describeType(t),
            customerDescription(t.description),
            isFinite(amount) ? amount.toFixed(2) : "",
            credit ? "Credit" : "Debit",
            t.status || ""
        ].map(cell).join(",");
    }

    function toCsv(transactions) {
        var lines = [COLUMNS.map(cell).join(",")];
        (transactions || []).forEach(function (t) { lines.push(row(t)); });
        // CRLF line endings are what spreadsheet software expects.
        return lines.join("\r\n") + "\r\n";
    }

    function fileName(now) {
        var d = now || new Date();
        function p(n) { return n < 10 ? "0" + n : "" + n; }
        return "melodexs-statement-" + d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + ".csv";
    }

    // The BOM makes Excel open the file as UTF-8 so the naira sign survives.
    function toBlob(csv) {
        return new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" });
    }

    var api = { COLUMNS: COLUMNS, toCsv: toCsv, cell: cell, fileName: fileName, toBlob: toBlob,
                customerDescription: customerDescription };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    root.MELODEXS_STATEMENT = api;
})(typeof window !== "undefined" ? window : globalThis);
