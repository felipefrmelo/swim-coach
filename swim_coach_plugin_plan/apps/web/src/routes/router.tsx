import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";

import { AppShell } from "../components/AppShell";
import type { Me } from "../api/types";
import { AvailabilityPage, DashboardPage, GarminPage, GoalsPage, PoolsPage, ProfilePage } from "./pages";

let authenticatedMe: Me;

const rootRoute = createRootRoute({ component: () => <AppShell me={authenticatedMe} /> });
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: DashboardPage });
const profileRoute = createRoute({ getParentRoute: () => rootRoute, path: "/profile", component: ProfilePage });
const poolsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/pools", component: PoolsPage });
const availabilityRoute = createRoute({ getParentRoute: () => rootRoute, path: "/availability", component: AvailabilityPage });
const goalsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/goals", component: GoalsPage });
const garminRoute = createRoute({ getParentRoute: () => rootRoute, path: "/garmin", component: GarminPage });

const routeTree = rootRoute.addChildren([indexRoute, profileRoute, poolsRoute, availabilityRoute, goalsRoute, garminRoute]);
export const router = createRouter({ routeTree });

export function setAuthenticatedMe(me: Me) { authenticatedMe = me; }

declare module "@tanstack/react-router" {
  interface Register { router: typeof router; }
}
