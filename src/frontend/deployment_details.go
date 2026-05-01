package main

import (
	"net/http"
	"os"
	"time"

	"cloud.google.com/go/compute/metadata"
	"github.com/sirupsen/logrus"
)

var deploymentDetailsMap map[string]string
var log *logrus.Logger

func init() {
	initializeLogger()
	// Initialize the map immediately with whatever we can get locally,
	// so the footer never shows "Deployment details are still loading."
	// GCP metadata calls run in a goroutine and fill in extra fields if available.
	deploymentDetailsMap = make(map[string]string)

	// Always available: hostname of the current container / machine
	if hostname, err := os.Hostname(); err == nil {
		deploymentDetailsMap["HOSTNAME"] = hostname
	}

	// Attempt GCP metadata calls in background — no-op on local/Docker/AWS
	go enrichWithGCPMetadata()
}

func initializeLogger() {
	log = logrus.New()
	log.Level = logrus.DebugLevel
	log.Formatter = &logrus.JSONFormatter{
		FieldMap: logrus.FieldMap{
			logrus.FieldKeyTime:  "timestamp",
			logrus.FieldKeyLevel: "severity",
			logrus.FieldKeyMsg:   "message",
		},
		TimestampFormat: time.RFC3339Nano,
	}
	log.Out = os.Stdout
}

// enrichWithGCPMetadata tries to fetch cluster/zone from the GCP metadata server.
// On non-GCP environments (local Docker, AWS, etc.) these calls will simply fail
// and the map keeps whatever was set during init — no error shown to the user.
func enrichWithGCPMetadata() {
	metaClient := metadata.NewClient(&http.Client{})

	if cluster, err := metaClient.InstanceAttributeValue("cluster-name"); err == nil && cluster != "" {
		deploymentDetailsMap["CLUSTERNAME"] = cluster
	}

	if zone, err := metaClient.Zone(); err == nil && zone != "" {
		deploymentDetailsMap["ZONE"] = zone
	}

	log.WithFields(logrus.Fields{
		"cluster":  deploymentDetailsMap["CLUSTERNAME"],
		"zone":     deploymentDetailsMap["ZONE"],
		"hostname": deploymentDetailsMap["HOSTNAME"],
	}).Debug("Deployment details loaded")
}