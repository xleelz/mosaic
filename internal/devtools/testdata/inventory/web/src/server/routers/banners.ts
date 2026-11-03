import { router, adminProcedure } from "../trpc";

export const bannersRouter = router({
  list: adminProcedure.query(async () => []),
  create: adminProcedure.input(x).mutation(async () => null),
});
