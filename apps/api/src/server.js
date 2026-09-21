require("dotenv").config();

const { app } = require("./app");

const PORT = Number(process.env.PORT || 3000);

if (require.main === module) {
    app.listen(PORT, () => {
        console.log(`MELODEXS CONNECT is running at http://localhost:${PORT}`);
    });
}

module.exports = app;
