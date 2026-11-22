import { cookies } from "next/headers";
import { COOKIE, unseal } from "./session-codec";
export * from "./session-codec";
export function session() { return unseal(cookies().get(COOKIE)?.value); }
