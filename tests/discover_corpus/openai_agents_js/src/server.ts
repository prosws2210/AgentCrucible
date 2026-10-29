import express from "express";
import { run } from "@openai/agents";
import { frontDesk } from "./agents";

const app = express();
app.use(express.json());

app.post("/chat", async (req, res) => {
  try {
    const result = await run(frontDesk, req.body.message, { maxTurns: 10 });
    res.json({ agent: result.lastAgent?.name, reply: result.finalOutput });
  } catch (err) {
    res.status(500).json({ error: String(err) });
  }
});

app.listen(Number(process.env.PORT ?? 3000), () => console.log("order-desk listening"));
