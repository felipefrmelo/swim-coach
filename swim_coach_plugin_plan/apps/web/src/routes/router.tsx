import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";

import { AppShell } from "../components/AppShell";
import type { Me } from "../api/types";
import { AvailabilityPage, DashboardPage, GarminPage, GoalsPage, PoolsPage, ProfilePage } from "./pages";
import { CalendarPage, NewWorkoutPage, WorkoutDetailPage, WorkoutsPage } from "./workouts";
import { ActivitiesPage, ActivityDetailPage } from "./activities";
import { OperationsPage } from "./operations";

let authenticatedMe: Me;

const rootRoute = createRootRoute({ component: () => <AppShell me={authenticatedMe} /> });
const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: DashboardPage });
const profileRoute = createRoute({ getParentRoute: () => rootRoute, path: "/profile", component: ProfilePage });
const poolsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/pools", component: PoolsPage });
const availabilityRoute = createRoute({ getParentRoute: () => rootRoute, path: "/availability", component: AvailabilityPage });
const goalsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/goals", component: GoalsPage });
const garminRoute = createRoute({ getParentRoute: () => rootRoute, path: "/garmin", component: GarminPage });
const workoutsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/workouts", component: WorkoutsPage });
const newWorkoutRoute = createRoute({ getParentRoute: () => rootRoute, path: "/workouts/new", component: NewWorkoutPage });
const workoutDetailRoute = createRoute({ getParentRoute: () => rootRoute, path: "/workouts/$workoutId", component: WorkoutDetailPage });
const calendarRoute = createRoute({ getParentRoute: () => rootRoute, path: "/calendar", component: CalendarPage });
const activitiesRoute = createRoute({ getParentRoute: () => rootRoute, path: "/activities", component: ActivitiesPage });
const activityDetailRoute = createRoute({ getParentRoute: () => rootRoute, path: "/activities/$activityId", component: ActivityDetailPage });
const operationsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/operations", component: OperationsPage });

const routeTree = rootRoute.addChildren([indexRoute, profileRoute, poolsRoute, availabilityRoute, goalsRoute, garminRoute, workoutsRoute, newWorkoutRoute, workoutDetailRoute, calendarRoute, activitiesRoute, activityDetailRoute, operationsRoute]);
export const router = createRouter({ routeTree });

export function setAuthenticatedMe(me: Me) { authenticatedMe = me; }

declare module "@tanstack/react-router" {
  interface Register { router: typeof router; }
}
