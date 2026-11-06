import { Type } from "typebox";
import net from "node:net";

export default function (pi: any) {
  const socket = process.env.C06_NATIVE_SOCKET;
  if (!socket) throw new Error("Missing experiment bridge socket");
  function request(value: any): Promise<any> {
    return new Promise((resolve, reject) => {
      const conn = net.createConnection(socket);
      let data = "";
      conn.setTimeout(40000, () => conn.destroy(new Error("Bridge timeout")));
      conn.on("connect", () => conn.write(JSON.stringify(value) + "\n"));
      conn.on("data", chunk => {
        data += chunk.toString();
        if (data.length > 4000000) conn.destroy(new Error("Oversized bridge response"));
        if (data.includes("\n")) {
          conn.end();
          try {
            const result = JSON.parse(data.split("\n")[0]);
            if (!result.ok) reject(new Error(result.error));
            else resolve(result);
          } catch (error) { reject(error); }
        }
      });
      conn.on("error", reject);
      conn.on("end", () => { if (!data.includes("\n")) reject(new Error("Bridge closed")); });
    });
  }
  const schemas: Record<string, any> = {
    list_dir: Type.Object({path: Type.Optional(Type.String())}, {additionalProperties: false}),
    grep: Type.Object({pattern: Type.String(), glob: Type.Optional(Type.String())}, {additionalProperties: false}),
    read_file: Type.Object({path: Type.String(), start_line: Type.Optional(Type.Integer({minimum:1})), end_line: Type.Optional(Type.Integer({minimum:1}))}, {additionalProperties: false}),
  };
  const descriptions: Record<string,string> = {
    list_dir: "List eligible repository paths in a directory; default path is .",
    grep: "Search eligible files using a POSIX extended regex and optional glob; at most 50 matches.",
    read_file: "Read an eligible repository-relative file with numbered lines, at most 400 lines.",
  };
  for (const name of Object.keys(schemas)) {
    pi.registerTool({name, label:name, description:descriptions[name], parameters:schemas[name],
      async execute(id: string, args: any) {
        try {
          const result = await request({op:"tool", id, name, args});
          if (result.exhausted) pi.setActiveTools([]);
          return {content:[{type:"text",text:result.text}],details:{budget_exhausted:result.exhausted}};
        } catch (error) {
          process.stderr.write("C06 native bridge failed: " + String(error) + "\n");
          process.exit(70); // Pi swallows hook exceptions; fail before further API use.
        }
      },
    });
  }
  pi.on("session_start", () => pi.setActiveTools(Object.keys(schemas)));
  pi.on("before_provider_request", async (event: any) => {
    try {
      await request({op:"before_request",tool_names:(event.payload?.tools || []).map((tool:any) => tool.function?.name || tool.name)});
    } catch (error) {
      process.stderr.write("C06 provider gate stopped: " + String(error) + "\n");
      process.exit(70); // Must terminate: an ordinary thrown hook error is swallowed.
    }
  });
  pi.on("message_end", async (event: any) => {
    if (event.message?.role !== "assistant") return;
    try { await request({op:"after_request", message:event.message}); }
    catch (error) {
      process.stderr.write("C06 billing gate stopped: " + String(error) + "\n");
      process.exit(70);
    }
  });
}
