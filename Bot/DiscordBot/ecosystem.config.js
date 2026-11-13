// PM2 process definition.
//   pm2 start ecosystem.config.js
//   pm2 save
//
// The interpreter MUST be the venv python, otherwise main.py cannot import
// discord and pm2 will restart-loop on ModuleNotFoundError.
module.exports = {
  apps: [
    {
      name: "discord-bot",
      script: "main.py",
      interpreter: process.env.PYTHON || `${__dirname}/venv/bin/python`,
      cwd: __dirname,
      autorestart: true,
      max_restarts: 20,
      restart_delay: 5000,
      kill_timeout: 15000,
      time: true,
      out_file: `${__dirname}/data/pm2-out.log`,
      error_file: `${__dirname}/data/pm2-error.log`,
      merge_logs: true,
    },
  ],
};
